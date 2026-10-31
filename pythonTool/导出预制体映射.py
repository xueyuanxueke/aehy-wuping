# -*- coding: utf-8 -*-
"""从 PlaceConstants.cctor 提取 prefabMap（世界物件 id → 预制体路径）。

这是什么
--------
存档里的 `wpType` 是**世界物件 id**，不是 `Wuping` 物品 id。两者靠游戏自己的两张常量表相连：

    PlaceConstants.prefabMap      : Dictionary<float,string>   → 物件 id ⇒ 预制体路径
    PlaceConstants.couldFindWuping: Dictionary<Wuping,float[]> → 物品   ⇒ 物件 id 数组

本脚本只解第一张，产物 `data/预制体映射.json`（620 条 / 261030），供
`导出物件变体.py` 判断每个物件的预制体与变体（地面/树上/雪地/巢）。

难点
----
字典是 cctor 里现造的：`array_new` 建数组 → 逐项 `str` 写值 → `Dictionary<float,object>.Add`。
键是 float（位模式），值是托管字符串，取值链是三层：

    ldr rX,[pc,#off]   ; 池字 = 相对偏移
    ldr rX,[pc,rX]     ; pc+8+off = GOT 项（R_ARM_RELATIVE 把内容填成字面量槽地址）
    ldr rY,[rX]        ; 槽内容 = Il2CppString*
    str rY,[rArr,...]  ; 或直接作为 Add 的 value

所以要先建 GOT→字面量槽映射（`.rel.dyn` 类型 23，加数存在目标地址的文件内容里），
字面量槽 → 字符串用 Il2CppDumper 的 `stringliteral.json`。

用法
----
    python pythonTool/导出预制体映射.py                      # 默认 261030
    python pythonTool/导出预制体映射.py --version-dir D:/Game/Unity/260109
    python pythonTool/导出预制体映射.py --out data/预制体映射.json
"""
import argparse
import bisect
import io
import json
import os
import re
import struct
import sys

try:
    from elftools.elf.elffile import ELFFile
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
except ImportError:
    sys.exit("需要 pyelftools 与 capstone：pip install pyelftools capstone")

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # 物资一览/
DEF_VERSION = os.environ.get("AEHY_VERSION_DIR") or os.path.join(
    os.path.dirname(ROOT), "261030")
DEF_OUT = os.path.join(ROOT, "data", "预制体映射.json")

REG_ALIAS = {"sp": 13, "lr": 14, "pc": 15, "ip": 12, "fp": 11, "sb": 9, "sl": 10}


def regnum(tok):
    tok = tok.strip().strip("{}[]")
    if tok in REG_ALIAS:
        return REG_ALIAS[tok]
    m = re.fullmatch(r"r(\d+)", tok)
    return int(m.group(1)) if m else -1


class Elf(object):
    def __init__(self, path):
        self.f = open(path, "rb")
        self.e = ELFFile(self.f)
        self.segs = [(s["p_vaddr"], s["p_vaddr"] + s["p_filesz"], s["p_offset"])
                     for s in self.e.iter_segments() if s["p_type"] == "PT_LOAD"]

    def read(self, va, n=4):
        for a, b, o in self.segs:
            if a <= va < b:
                self.f.seek(o + (va - a))
                return self.f.read(n)
        return None

    def u32(self, va):
        b = self.read(va, 4)
        return struct.unpack("<I", b)[0] if b else None


def load_strings(path):
    return {int(i["address"], 16): i["value"] for i in json.load(open(path, encoding="utf-8"))}


def load_got(elf, lo, hi):
    """GOT 项 → 字面量槽地址（只保留指向字符串字面量的那批）"""
    got = {}
    sec = elf.e.get_section_by_name(".rel.dyn")
    if sec is None:
        return got
    for r in sec.iter_relocations():
        if r["r_info_type"] != 23:               # R_ARM_RELATIVE
            continue
        b = elf.read(r["r_offset"], 4)
        if not b:
            continue
        add = struct.unpack("<I", b)[0]
        if lo <= add <= hi:
            got[r["r_offset"]] = add
    return got


def decode_range(elf, start, end, md):
    """逐字解码：数据池/跳转表会让 capstone 停住，遇到就跳 4 字节继续"""
    buf = elf.read(start, end - start)
    out, a = [], start
    while a < end:
        ins = None
        for x in md.disasm(buf[a - start:a - start + 4], a):
            ins = x
        if ins is None:
            a += 4
            continue
        out.append(ins)
        a += ins.size
    return out


def find_cctor(script):
    for m in script["ScriptMethod"]:
        if m["Name"].endswith("PlaceConstants$$.cctor") or \
           m["Name"].endswith("PlaceConstants___cctor"):
            return m["Address"]
    raise SystemExit("script.json 里找不到 PlaceConstants$$.cctor")


def func_end(script, addr):
    addrs = sorted({m["Address"] for m in script["ScriptMethod"]} | set(script["Addresses"]))
    i = bisect.bisect_right(addrs, addr)
    return addrs[i] if i < len(addrs) else addr + 0x10000


def f32_to_int(bits):
    """float 位模式 → 整数 id（字典键是 float，值域 0..4096 的整数）"""
    try:
        v = struct.unpack("<f", struct.pack("<I", bits & 0xFFFFFFFF))[0]
    except struct.error:
        return None
    if v != v or abs(v) > 1e6:                   # NaN / 越界
        return None
    return int(round(v))


def extract(version_dir, dumper_dir, verbose=True):
    so = os.path.join(version_dir, "libil2cpp.so")
    meta_json = os.path.join(dumper_dir, "stringliteral.json")
    script_json = os.path.join(dumper_dir, "script.json")
    for p in (so, meta_json, script_json):
        if not os.path.exists(p):
            raise SystemExit("找不到 %s" % p)

    elf = Elf(so)
    sl = load_strings(meta_json)
    lo, hi = min(sl), max(sl)
    got = load_got(elf, lo, hi)
    if verbose:
        print("字面量槽 %d 条，GOT 项 %d 条" % (len(sl), len(got)))

    script = json.load(open(script_json, encoding="utf-8"))

    # 注意：同名的 .ctor 有 9 个重载（不同参数个数），必须按「地址集合」判断，
    # 否则用 {名字: 地址} 建字典会被后面的重载覆盖掉。
    def addrs_of(suffix):
        return {m["Address"] for m in script["ScriptMethod"] if m["Name"].endswith(suffix)}

    cctor = find_cctor(script)
    end = func_end(script, cctor)
    add_f = addrs_of("Dictionary<float, object>$$Add")
    ctor_f = addrs_of("Dictionary<float, object>$$.ctor")
    add_i = addrs_of("Dictionary<Int32Enum, object>$$Add")
    ctor_i = addrs_of("Dictionary<Int32Enum, object>$$.ctor")
    if not (add_f and ctor_f):
        raise SystemExit("找不到 Dictionary<float,object> 的 Add/.ctor")
    add_all, ctor_all = add_f | add_i, ctor_f | ctor_i

    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    ins = decode_range(elf, cctor, end, md)
    if verbose:
        print("cctor %#x..%#x（解码 %d 条）   Add(float)@%#x  Add(enum)@%s"
              % (cctor, end, len(ins), min(add_f), ("%#x" % min(add_i)) if add_i else "n/a"))

    regs, groups, cur, pend = {}, [], None, [None]

    def kill(r):
        if r >= 0:
            regs.pop(r, None)

    for it in ins:
        mn, op, ad = it.mnemonic, it.op_str, it.address

        if mn in ("bl", "blx"):
            try:
                t = int(op.lstrip("#"), 16)
            except ValueError:
                t = -1
            if t in ctor_all:
                cur = {"kind": "float" if t in ctor_f else "int", "at": ad, "items": []}
                groups.append(cur)
            elif t in add_all and cur is not None:
                k, v = regs.get(1), regs.get(2)
                key = k[1] if k and k[0] == "c" else None
                val = None
                if v:
                    if v[0] == "str":
                        val = v[1]
                    elif v[0] == "arr":
                        val = None                   # 本表不用数组值
                cur["items"].append((key, val))
            for r in (0, 1, 2, 3, 12, 14):
                kill(r)
            continue

        if mn in ("mov", "movs", "movw", "movt"):
            p = [x.strip() for x in op.split(",")]
            if len(p) != 2:
                continue
            d = regnum(p[0])
            if d < 0:
                continue
            if p[1].startswith("#"):
                try:
                    val = int(p[1][1:], 0)
                except ValueError:
                    kill(d)
                    continue
                if mn == "movt":
                    old = regs.get(d)
                    base = old[1] if old and old[0] == "c" else 0
                    regs[d] = ("c", (base & 0xFFFF) | (val << 16))
                else:
                    regs[d] = ("c", val & 0xFFFFFFFF)
            else:
                s = regnum(p[1])
                kill(d)
                if s in regs:
                    regs[d] = regs[s]
            continue

        if mn in ("add", "adds", "sub", "subs"):
            p = [x.strip() for x in op.split(",")]
            d = regnum(p[0])
            if d < 0:
                continue
            if len(p) >= 3 and p[2].startswith("#"):
                s = regnum(p[1])
                try:
                    val = int(p[2][1:], 0)
                except ValueError:
                    kill(d)
                    continue
                st = regs.get(s)
                if st and st[0] == "c":
                    regs[d] = ("c", ((st[1] + val) if mn.startswith("add")
                                     else (st[1] - val)) & 0xFFFFFFFF)
                else:
                    kill(d)
            else:
                kill(d)
            continue

        if mn in ("ldr", "ldrb", "ldrh"):
            m = re.match(r"^(\w+),\s*\[([^\]]+)\]", op)
            if not m:
                continue
            d = regnum(m.group(1))
            parts = [x.strip() for x in m.group(2).split(",")]
            base = regnum(parts[0])
            if base == 15 and len(parts) == 2 and not parts[1].startswith("#"):
                s = regs.get(regnum(parts[1]))
                kill(d)
                if s and s[0] == "off":
                    tgt = (ad + 8 + s[1]) & 0xFFFFFFFF
                    regs[d] = ("slot", got[tgt]) if tgt in got else ("heap", tgt)
                continue
            if base == 15:                            # ldr rX,[pc,#imm] → 池字
                w = struct.unpack("<I", it.bytes)[0]
                imm = w & 0xFFF
                if not (w >> 23) & 1:
                    imm = -imm
                W = elf.u32(ad + 8 + imm)
                regs[d] = ("off", W) if W is not None else ("heap", 0)
                continue
            if len(parts) > 1:                        # ldr rX,[rY,#imm]
                kill(d)
                continue
            s = regs.get(base)                        # ldr rX,[rY] → 取字符串
            kill(d)
            if s and s[0] == "slot":
                regs[d] = ("str", sl.get(s[1], ""))
            continue

        if mn == "str":
            continue                                  # 本表不需要数组元素
        if mn == "pop":
            for t in op.strip("{}").split(","):
                kill(regnum(t))
            continue

    # 选表：字符串值最多、键落在 0..4096 的那一组
    best, best_n = None, 0
    for g in groups:
        items = [(f32_to_int(k) if g["kind"] == "float" else k, v)
                 for k, v in g["items"] if isinstance(k, int)]
        items = [(k, v) for k, v in items
                 if isinstance(v, str) and v and k is not None and 0 <= k <= 4096]
        if len(items) > best_n:
            best, best_n = items, len(items)
    if not best:
        raise SystemExit("没找到像 prefabMap 的字典（键为物件 id、值为预制体路径）")

    table = {}
    for k, v in best:
        table[k] = v
    if verbose:
        print("候选 %d 条 → 去重后 %d 条，键范围 %d..%d"
              % (best_n, len(table), min(table), max(table)))
    return table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version-dir", default=DEF_VERSION,
                    help="版本目录（含 libil2cpp.so），默认 261030")
    ap.add_argument("--dumper-dir", default=None,
                    help="Il2CppDumper 输出目录，默认 <version-dir>/Il2CppDumper-out")
    ap.add_argument("--out", default=DEF_OUT)
    ap.add_argument("--compare", default=None,
                    help="可选：与另一份旧表逐条比对（验证提取正确性）")
    a = ap.parse_args()

    dumper = a.dumper_dir or os.path.join(a.version_dir, "Il2CppDumper-out")
    table = extract(a.version_dir, dumper)

    if a.compare and os.path.exists(a.compare):
        old = {int(k): v for k, v in json.load(open(a.compare, encoding="utf-8")).items() if v}
        common = set(table) & set(old)
        same = [k for k in common if table[k] == old[k]]
        print("与 %s 比对：交集 %d，一致 %d，冲突 %d，新增 %d"
              % (os.path.basename(a.compare), len(common), len(same),
                 len(common) - len(same), len(set(table) - set(old))))
        for k in common:
            if table[k] != old[k]:
                print("  冲突 id=%d  旧=%s  新=%s" % (k, old[k], table[k]))
                break

    obj = {
        "meta": {
            "title": "预制体映射（PlaceConstants.prefabMap）",
            "desc": "世界物件 id → 预制体资源路径。存档 wpType 用的就是这套 id，"
                    "与 Wuping 物品 id 不是一回事。",
            "source": "libil2cpp.so 的 PlaceConstants$$.cctor（Dictionary<float,string>）",
            "versionDir": os.path.basename(a.version_dir),
            "levels": len(table),
        },
        "prefabs": {str(k): v for k, v in sorted(table.items())},
    }
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=0)
    print("已写出 %s（%d 条）" % (a.out, len(table)))


if __name__ == "__main__":
    main()
