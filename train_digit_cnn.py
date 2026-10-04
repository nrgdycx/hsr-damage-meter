# -*- coding: utf-8 -*-
"""
数字分类器训练 —— 小 CNN，输入 1×34×24 灰度字形，输出 0~9。

为什么用 CNN 而不是模板匹配（前面几轮的教训）：
  * 同一数值在 HUD 上会停留 1~1.5 秒，字形有出现动画（缩放/透明度渐变）；
  * 数字有【两种字号】（累积阶段小、结算时大）；
  * 字形带【金色辉光】，厚度逐帧不同。
  → 手工二值化+像素差比对（实测最好只有 70%，多数情况 20~50%）对这种形变不鲁棒；
    CNN + 强增强（位移/缩放/亮度/形态学/噪声）能学到不变性。

评测方式：**留一"帧"交叉验证**（同一帧的字形不允许跨训练/测试集），
         这是唯一能反映"换一帧还能不能读对"的评估方式。

⚠️ A 线补充（重要）：数据只有百来个样本，**单次训练的随机性极大** ——
   同一条管线、只换 batch/seed，留出集就能在 26/29 和 29/29 之间跳。
   所以最终交付用**集成**（DigitEnsemble，多 seed 平均 logits），
   并把"单模型逐 seed 的分布"一起报出来，避免拿运气当水平。
"""

import json
import os
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA = "out/digit_dataset.npz"
MODEL_PT = "out/digit_cnn.pt"
MODEL_ENS = "out/digit_cnn_ens.pt"
MODEL_ONNX = "out/digit_cnn.onnx"
GW, GH = 24, 34
OPSET = 18         # 17 会让 onnxscript 走版本回退并报 AssertionError，18 原生支持
N_ENS = 9          # 集成成员数（CPU 上每个约 20~40s，9 个是精度/时间的折中）


class DigitCNN(nn.Module):
    def __init__(self, ncls=10):
        super().__init__()
        self.c1 = nn.Conv2d(1, 16, 3, padding=1)
        self.c2 = nn.Conv2d(16, 32, 3, padding=1)
        self.c3 = nn.Conv2d(32, 32, 3, padding=1)
        self.bn1 = nn.BatchNorm2d(16)
        self.bn2 = nn.BatchNorm2d(32)
        self.bn3 = nn.BatchNorm2d(32)
        self.fc1 = nn.Linear(32 * 4 * 3, 64)     # 34x24 → 17x12 → 8x6 → 4x3
        self.fc2 = nn.Linear(64, ncls)
        self.drop = nn.Dropout(0.3)

    def forward(self, x):
        x = F.max_pool2d(F.relu(self.bn1(self.c1(x))), 2)
        x = F.max_pool2d(F.relu(self.bn2(self.c2(x))), 2)
        x = F.max_pool2d(F.relu(self.bn3(self.c3(x))), 2)
        x = x.flatten(1)
        x = self.drop(F.relu(self.fc1(x)))
        return self.fc2(x)


def augment(x, gen):
    """随机位移 + 缩放 + 旋转 + 亮度/对比度 + 形态学(模拟辉光厚薄) + 噪声。"""
    n = x.shape[0]
    ang = torch.rand(n, generator=gen) * 12 - 6            # ±6°
    sc = 0.88 + torch.rand(n, generator=gen) * 0.24        # 0.88~1.12
    tx = (torch.rand(n, generator=gen) * 2 - 1) * 0.16     # ±16% 平移
    ty = (torch.rand(n, generator=gen) * 2 - 1) * 0.16
    theta = torch.zeros(n, 2, 3)
    theta[:, 0, 0] = torch.cos(ang * np.pi / 180) / sc
    theta[:, 0, 1] = -torch.sin(ang * np.pi / 180) / sc
    theta[:, 1, 0] = torch.sin(ang * np.pi / 180) / sc
    theta[:, 1, 1] = torch.cos(ang * np.pi / 180) / sc
    theta[:, 0, 2] = tx
    theta[:, 1, 2] = ty
    grid = F.affine_grid(theta, x.shape, align_corners=False)
    x = F.grid_sample(x, grid, align_corners=False, padding_mode="zeros")
    # 亮度/对比度
    x = x * (0.7 + torch.rand(n, 1, 1, 1, generator=gen) * 0.6)
    x = x + (torch.rand(n, 1, 1, 1, generator=gen) - 0.5) * 0.25
    # 形态学：随机腐蚀/膨胀，模拟辉光厚薄
    if torch.rand(1, generator=gen).item() < 0.5:
        x = F.max_pool2d(x, 2, stride=1, padding=1)         # 膨胀
    else:
        x = -F.max_pool2d(-x, 2, stride=1, padding=1)       # 腐蚀
    x = (x + torch.randn(x.shape, generator=gen) * 0.05).clamp(0, 1)
    return x


def train_one(Xtr, ytr, epochs=260, seed=0, verbose=False, bs=16):
    """训练一个分类器。

    bs：批大小。默认 16 与历史结果一致；调大（如 64，或直接抓满）在 CPU 上快数倍，
    A 线做对比实验/交叉验证时用它换时间。
    """
    torch.manual_seed(seed)
    gen = torch.Generator().manual_seed(seed)
    model = DigitCNN()
    opt = torch.optim.Adam(model.parameters(), lr=2e-3, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    Xtr = torch.tensor(Xtr, dtype=torch.float32)
    ytr = torch.tensor(ytr, dtype=torch.long)
    # 类不平衡 → 加权
    cnt = np.bincount(ytr.numpy(), minlength=10).astype(np.float32)
    w = torch.tensor(np.where(cnt > 0, cnt.sum() / np.maximum(cnt, 1), 0), dtype=torch.float32)
    lossf = nn.CrossEntropyLoss(weight=w / w.sum() * 10)
    model.train()
    n = len(ytr)
    for ep in range(epochs):
        perm = torch.randperm(n, generator=gen)
        tot = 0.0
        for i in range(0, n, bs):
            idx = perm[i:i + bs]
            xb = augment(Xtr[idx], gen)
            loss = lossf(model(xb), ytr[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += float(loss.detach()) * len(idx)
        sched.step()
        if verbose and ep % 60 == 0:
            print("      ep%-4d loss %.4f" % (ep, tot / n))
    model.eval()
    return model


def predict(model, X):
    with torch.no_grad():
        return model(torch.tensor(X, dtype=torch.float32)).argmax(1).numpy()


class DigitEnsemble(nn.Module):
    """
    多个 DigitCNN 的集成（对 logits 取平均）。

    为什么需要：数据只有百来个样本，单次训练的随机性极大 —— 同一个管线、
    只换 batch/seed，留出集就能从 26/29 跳到 29/29。评测单次模型等于在看噪声。
    集成把"这次运气好不好"这件事平均掉；前向仍是毫秒级，不违反实时要求。
    """

    def __init__(self, models=None):
        super().__init__()
        self.members = nn.ModuleList(models or [])

    def forward(self, x):
        return torch.stack([m(x) for m in self.members], 0).mean(0)

    @property
    def n(self):
        return len(self.members)


def train_ensemble(X, y, n=9, epochs=260, bs=64, seed0=7):
    members = []
    for k in range(n):
        members.append(train_one(X, y, epochs=epochs, seed=seed0 + k, bs=bs))
    return DigitEnsemble(members)


def tta_logits(model, X):
    """测试时增强：小幅平移/缩放后取平均 logits（对形变更稳）。返回 tensor。"""
    x = torch.tensor(X, dtype=torch.float32)
    outs = []
    for dx, dy, sc in ((0, 0, 1.0), (0.06, 0, 1.0), (-0.06, 0, 1.0), (0, 0.06, 1.0),
                       (0, -0.06, 1.0), (0, 0, 0.94), (0, 0, 1.06)):
        theta = torch.zeros(x.shape[0], 2, 3)
        theta[:, 0, 0] = 1.0 / sc
        theta[:, 1, 1] = 1.0 / sc
        theta[:, 0, 2] = dx
        theta[:, 1, 2] = dy
        grid = F.affine_grid(theta, x.shape, align_corners=False)
        outs.append(model(F.grid_sample(x, grid, align_corners=False, padding_mode="zeros")))
    with torch.no_grad():
        return torch.stack(outs, 0).mean(0)


def save_ensemble(model, path=MODEL_ENS, canonical_path=MODEL_PT):
    """
    集成同时写两份：`_ens.pt` 与 `digit_cnn.pt`。

    为什么 `digit_cnn.pt` 也放集成：B 线的契约是"实时用的 .onnx 必须与 .pt 同源"。
    如果 .pt 是单模型而 .onnx 是集成（或反过来），离线评测与实时读数就是两个模型 ——
    B 线已经实测过这种坑（旧 ONNX 导致 t=105 的 4↔6 直接读错）。
    所以规范模型 = 集成，`.pt` / `.onnx` / 探针三者都由它派生。
    """
    ck = {"members": [m.state_dict() for m in model.members], "gw": GW, "gh": GH}
    torch.save(ck, path)
    torch.save(ck, canonical_path)


def load_any_pt(path=MODEL_PT):
    """统一加载入口：兼容集成 {'members':[...]} 与旧版单模型 {'state':...}。"""
    ck = torch.load(path, map_location="cpu", weights_only=False)
    if "members" in ck:
        ms = []
        for sd in ck["members"]:
            m = DigitCNN()
            m.load_state_dict(sd)
            m.eval()
            ms.append(m)
        return DigitEnsemble(ms)
    m = DigitCNN()
    m.load_state_dict(ck["state"])
    m.eval()
    return m


def load_ensemble(path=MODEL_ENS):
    return load_any_pt(path)


def main():
    d = np.load(DATA, allow_pickle=True)
    X, y = d["X"], d["y"]
    meta = [json.loads(m) for m in d["meta"]]
    frames = sorted(set(m["t"] for m in meta))
    print("样本 %d，来源帧 %d 个: %s" % (len(y), len(frames), frames))
    print("标签分布: %s" % dict(zip(*[a.tolist() for a in np.unique(y, return_counts=True)])))

    # ── 留一"帧"交叉验证（很慢：帧数 × (1+3) 个模型，用 --cv 显式开启）──
    if "--cv" in sys.argv:
        print("\n留一帧交叉验证（同一帧不跨训练/测试集）:")
        tot = ok_s = ok_e = 0
        for held in frames:
            te = np.array([i for i, m in enumerate(meta) if m["t"] == held])
            tr = np.array([i for i, m in enumerate(meta) if m["t"] != held])
            if len(tr) == 0:
                continue
            m1 = train_one(X[tr], y[tr], seed=held, bs=64)
            p1 = predict(m1, X[te])
            ens = train_ensemble(X[tr], y[tr], n=3, seed0=held, bs=64)
            pe = predict(ens, X[te])
            ok_s += int((p1 == y[te]).sum())
            ok_e += int((pe == y[te]).sum())
            tot += len(te)
            print("   留出 t=%-4s 单模型 %d/%d   集成(n=3) %d/%d   %s" % (
                held, int((p1 == y[te]).sum()), len(te), int((pe == y[te]).sum()), len(te),
                "".join("[ok]" if p == t else "[x%d=%d]" % (t, p) for p, t in zip(pe, y[te]))), flush=True)
        if tot:
            print("\n逐字准确率（留一帧）: 单模型 %.1f%%   集成 %.1f%%" % (
                ok_s / tot * 100, ok_e / tot * 100))
    else:
        print("（跳过留一帧交叉验证；要跑加 --cv，约 1 小时）")

    # ── 全量训练 + 导出 ──
    print("\n用全部数据训练最终集成模型（%d 个成员）…" % N_ENS, flush=True)
    ens = train_ensemble(X, y, n=N_ENS, epochs=400, bs=64, seed0=7)
    print("   集成训练集自检: %.1f%%（仅参考）" % (float((predict(ens, X) == y).mean()) * 100))
    save_ensemble(ens)
    print("   已保存", MODEL_ENS, "（%d 成员）与" % ens.n, MODEL_PT, "（单模型备份）")
    try:
        torch.onnx.export(ens, torch.zeros(1, 1, GH, GW), MODEL_ONNX,
                          input_names=["img"], output_names=["logits"],
                          dynamic_axes={"img": {0: "n"}, "logits": {0: "n"}}, opset_version=OPSET)
        print("   已导出 ONNX（集成，供实时 onnxruntime 使用）:", MODEL_ONNX)
    except Exception as e:
        print("   集成 ONNX 导出失败(%s)，退回导出单个成员" % repr(e)[:80])
        torch.onnx.export(ens.members[0], torch.zeros(1, 1, GH, GW), MODEL_ONNX,
                          input_names=["img"], output_names=["logits"],
                          dynamic_axes={"img": {0: "n"}, "logits": {0: "n"}}, opset_version=OPSET)
        print("   已导出 ONNX（单成员）:", MODEL_ONNX)


if __name__ == "__main__":
    main()
