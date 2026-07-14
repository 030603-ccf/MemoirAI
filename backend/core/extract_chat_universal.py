# -*- coding: utf-8 -*-
"""
extract_chat_universal.py
==========================
通用聊天记录截图 OCR 提取（基于消息左右位置判断）。

不依赖颜色，适配任何聊天软件：
  - 微信、QQ、Telegram、短信、企业微信、iMessage
  - 任何"左侧 = 对方 / 右侧 = 本人"布局的对话界面

原理：
  1. PaddleOCR 识别整张截图（不分离）
  2. 每个 OCR 结果带 bounding box（4 个角点）
  3. 计算 bbox 质心 X 坐标
  4. 跟图片宽度中点比较：
     - 质心 < 中点 → 左侧 → 对方
     - 质心 > 中点 → 右侧 → 本人
     - 质心在中部 ±20% → 系统消息（居中）
  5. 按 Y 坐标排序，合并相邻行（OCR 切碎的情况）
  6. 过滤掉时间戳、状态栏、昵称行、气泡提示等噪音

默认行为（无参数）：
  - 自动遍历 ./chat_data/screenshots/ 下的所有图片
  - 输出到 ./chat_data/chat_extracted.txt

用法：
  # 默认（遍历 chat_data/screenshots/）
  python extract_chat_universal.py

  # 指定目录
  python extract_chat_universal.py my_screenshots/

  # 单张图 + 调试
  python extract_chat_universal.py shot.png --debug

  # 裁剪顶部 250 像素（去掉状态栏 + 标题栏）
  python extract_chat_universal.py --crop-top 250
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np


# ============================================================
#  时间戳 / 状态栏 / 昵称 / 气泡提示 噪音过滤
# ============================================================
TIMESTAMP_PATTERNS = [
    r'^\d{1,2}:\d{2}$',                                       # 10:30
    r'^\d{1,2}:\d{2}\D',                                      # 10:30 后面跟非数字（昵称合并）
    r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}\s*\d{1,2}:\d{2}',     # 2024-05-12 10:30
    r'^(上午|下午|晚上|凌晨|清晨)\s*\d{1,2}:\d{2}',
    r'^(昨天|今天|前天)\s*\d{1,2}:\d{2}',
    r'^(昨天|今天|前天)$',
    r'^(周一|周二|周三|周四|周五|周六|周天|星期[一二三四五六日])',
    r'^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}$',
    r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)',
]

NOISE_PATTERNS = [
    # 微信气泡被截断提示（出现在消息末尾的"…更多信息"）
    r'更[^\u4e00-\u9fa5]{0,2}多.{0,4}信息',  # "更多""更x多""更多+信息"
    r'^\.…{1,5}.{0,5}更.{0,3}多(信息)?$',
    r'^\.{2,}.{0,5}更.{0,3}多(信息)?$',
    r'^点击查看.*$',
    r'^.{0,4}更多信息\s*$',
    r'^.{0,4}\.{2,}\s*更.{0,3}多\s*$',
    # 撤回提示
    r'^.{0,5}撤回了一条消息\s*$',
    r'^你撤回了一条消息$',
    # 状态栏常见模式
    r'.*\d+\.?\d*\s*KB/s.*',              # 网速
    r'.*\d+\.?\d*\s*MB/s.*',              # 网速
    r'.*\d+\.?\d*\s*GB/s.*',              # 网速
    r'^[*\$¥]\s*[A-Z]{2,}.*$',            # $ VPN / * 信号
    r'^\d+%\s*$',                          # 电池百分比
    r'^[A-Z]{2,}\s*\d+\.\d+\s*[KMG]?B',  # VPN 74.1KB
    r'.*5[Gg]\s*5[Gg]\s*\d+%.*',          # 5G 5G 46%
    # 纯符号
    r'^[\W_]+$',
    # OCR 错误产生的乱码（短且无语义）
    r'^[A-Z]{6,}$',                        # 大写字母连写 (e.g. TFXPNTFAH)
    r'^[a-zA-Z]{1,3}\d{2,5}$',            # 字母+数字乱码
]


def is_timestamp(text: str) -> bool:
    """判断是否为时间戳/系统消息"""
    text = text.strip()
    if not text:
        return True
    for p in TIMESTAMP_PATTERNS:
        if re.match(p, text):
            return True
    return False


def is_noise(text: str) -> bool:
    """判断是否为状态栏/昵称/气泡提示等噪音"""
    text = text.strip()
    if not text:
        return True

    # 时间戳（含昵称合并的情况）
    if is_timestamp(text):
        return True

    # 噪音模式
    for p in NOISE_PATTERNS:
        if re.search(p, text):
            return True

    return False


def compute_centroid(box) -> tuple:
    """bbox 4 角点的质心 (cx, cy)"""
    cx = sum(p[0] for p in box) / 4.0
    cy = sum(p[1] for p in box) / 4.0
    return cx, cy


def shift_box(box, dy):
    """bbox 整体向下偏移 dy 像素（裁剪后用）"""
    return [[p[0], p[1] + dy] for p in box]


# ============================================================
#  OCR
# ============================================================
def ocr_extract(ocr, img_input) -> list:
    """
    PaddleOCR 识别，返回 [{box, text, conf}, ...]
    img_input 可以是 Path 或 numpy.ndarray
    """
    try:
        result = ocr.predict(img_input)
    except (TypeError, AttributeError):
        result = ocr.ocr(img_input, cls=True)
    items = []
    if not result:
        return items

    # 旧版 paddleocr 返回: [[[box, (text, conf)], ...], ...]
    if isinstance(result, list) and result and isinstance(result[0], list):
        for line in result:
            if not line:
                continue
            for box, (text, conf) in line:
                items.append({'box': box, 'text': text.strip(), 'conf': float(conf)})
    # 新版 paddleocr 返回: [{'rec_text': ..., 'rec_score': ..., 'dt_polys': ...}, ...]
    elif isinstance(result, list) and result and isinstance(result[0], dict):
        for entry in result:
            text = entry.get('rec_text', '').strip()
            conf = float(entry.get('rec_score', 0))
            box = entry.get('dt_polys') or entry.get('rec_boxes') or entry.get('box')
            if box is None:
                continue
            if hasattr(box, 'tolist'):
                box = box.tolist()
            if box and isinstance(box[0], (int, float)):
                box = [box[:2], box[2:4], box[4:6], box[6:8]] if len(box) == 8 else box
            elif box and isinstance(box[0], list) and len(box[0]) == 2:
                pass
            items.append({'box': box, 'text': text, 'conf': conf})
    return items


# ============================================================
#  角色分类 / 合并 / 过滤
# ============================================================
def classify_by_position(items: list, img_w: int, threshold_ratio: float = 0.5,
                         center_band: float = 0.1):
    """根据质心 X 判断角色：左侧=对方，右侧=本人，中间=系统"""
    threshold_x = img_w * threshold_ratio
    band_w = img_w * center_band

    for it in items:
        cx, cy = compute_centroid(it['box'])
        it['cx'] = float(cx)
        it['cy'] = float(cy)
        it['y'] = float(it['box'][0][1])

        if cx < threshold_x - band_w:
            it['role'] = 'other'
        elif cx > threshold_x + band_w:
            it['role'] = 'self'
        else:
            it['role'] = 'system'
    return items


def merge_close_lines(items: list, y_tol: int = 20) -> list:
    """合并 Y 接近的同角色文本（OCR 切碎同一消息）"""
    if not items:
        return items
    items = sorted(items, key=lambda x: x['y'])
    result = [items[0]]
    for it in items[1:]:
        last = result[-1]
        if it['role'] == last['role'] and abs(it['y'] - last['y']) < y_tol:
            last['text'] = (last['text'] + it['text']).strip()
            last['conf'] = min(last['conf'], it['conf'])
        else:
            result.append(it)
    return result


def filter_items(items: list) -> list:
    """过滤掉系统消息 + 噪音"""
    return [it for it in items if it['role'] != 'system' and not is_noise(it['text'])]


# ============================================================
#  单图处理
# ============================================================
def split_long_image(img, max_height=6000):
    """
    把过高的图切成多块（避免 OpenCV warpPerspective 限制）。
    返回 [(y_offset, chunk_img), ...]
    """
    h, w = img.shape[:2]
    if h <= max_height:
        return [(0, img)]
    chunks = []
    y = 0
    while y < h:
        end = min(y + max_height, h)
        chunks.append((y, img[y:end, :]))
        y = end
    return chunks


def process_image(ocr, img_path: Path, threshold_ratio: float = 0.5,
                  center_band: float = 0.1, crop_top_px: int = 0,
                  debug: bool = False):
    img = cv2.imread(str(img_path))
    if img is None:
        print(f"  [skip] cannot read: {img_path}")
        return []

    h, w = img.shape[:2]
    crop_info = f", crop-top {crop_top_px}px" if crop_top_px > 0 else ""
    print(f"  [info] {img_path.name}: {w}x{h}, threshold x={w*threshold_ratio:.0f}{crop_info}")

    # 裁剪顶部
    if crop_top_px > 0:
        img = img[crop_top_px:, :]
        h = img.shape[0]

    # 长截图自动分块
    chunks = split_long_image(img, max_height=6000)
    if len(chunks) > 1:
        print(f"  [split] long image split into {len(chunks)} chunks")

    all_items = []
    for chunk_idx, (y_offset, chunk_img) in enumerate(chunks):
        if len(chunks) > 1:
            print(f"  [chunk {chunk_idx+1}/{len(chunks)}] {chunk_img.shape[1]}x{chunk_img.shape[0]} (y_offset={y_offset})")
        items = ocr_extract(ocr, chunk_img)
        # 还原 Y 坐标
        if y_offset > 0:
            for it in items:
                it['box'] = shift_box(it['box'], y_offset)
        all_items.extend(items)

    items = all_items
    print(f"  [ocr] {len(items)} raw text boxes (total)")

    # 还原 Y 坐标（裁剪后）
    if crop_top_px > 0:
        for it in items:
            it['box'] = shift_box(it['box'], crop_top_px)

    # 角色分类
    items = classify_by_position(items, w, threshold_ratio, center_band)

    # 排序 + 合并
    items.sort(key=lambda x: x['y'])
    items = merge_close_lines(items, y_tol=20)

    # 过滤
    before = len(items)
    items = filter_items(items)
    after = len(items)
    if before != after:
        print(f"  [filter] removed {before - after} system/timestamp/noise lines")

    # 调试可视化
    if debug:
        out_dir = img_path.parent / "_debug"
        out_dir.mkdir(exist_ok=True)
        dbg = img.copy()
        threshold_x = int(w * threshold_ratio)
        # 中线
        cv2.line(dbg, (threshold_x, 0), (threshold_x, h), (0, 255, 0), 1)
        # 裁剪线
        if crop_top_px > 0:
            cv2.line(dbg, (0, crop_top_px), (w, crop_top_px), (255, 0, 255), 1)

        color_map = {'self': (0, 0, 255), 'other': (255, 0, 0), 'system': (128, 128, 128)}
        for it in items:
            cx, cy = int(it['cx']), int(it['cy'])
            color = color_map.get(it['role'], (255, 255, 255))
            cv2.circle(dbg, (cx, cy), 10, color, -1)
            cv2.putText(dbg, it['text'][:8], (cx + 12, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        cv2.imwrite(str(out_dir / f"{img_path.stem}_classified.png"), dbg)
        print(f"  [debug] saved {out_dir}/{img_path.stem}_classified.png")

    return items


# ============================================================
#  收集图片
# ============================================================
def collect_images(path: Path) -> list:
    if path.is_file():
        return [path]
    files = []
    for ext in ('*.png', '*.jpg', '*.jpeg', '*.bmp', '*.webp'):
        files.extend(sorted(path.glob(ext)))
    return files


# ============================================================
#  Main
# ============================================================
def default_input_dir() -> Path:
    """默认输入：脚本同级的 chat_data/screenshots/"""
    return Path(__file__).parent / "chat_data" / "screenshots"


def default_output_path() -> Path:
    """默认输出：脚本同级的 chat_data/chat_extracted.txt"""
    return Path(__file__).parent / "chat_data" / "chat_extracted.txt"


def main():
    ap = argparse.ArgumentParser(description='Extract chat from messenger screenshots (universal)')
    ap.add_argument('input', nargs='?',
                    help='image file or directory (default: ./chat_data/screenshots/)')
    ap.add_argument('-o', '--output',
                    help='output text file (default: ./chat_data/chat_extracted.txt)')
    ap.add_argument('--json', action='store_true', help='also dump json')
    ap.add_argument('--debug', action='store_true', help='save classification debug image')
    ap.add_argument('--threshold', type=float, default=0.5,
                    help='left/right boundary ratio (0.5 = middle)')
    ap.add_argument('--center-band', type=float, default=0.1,
                    help='middle band width (relative, default 0.1 = 10%%)')
    ap.add_argument('--crop-top', type=int, default=0,
                    help='crop top N pixels (removes status bar / title bar)')
    ap.add_argument('--lang', default='ch', help='ocr language')
    args = ap.parse_args()

    # 默认路径
    in_path = Path(args.input) if args.input else default_input_dir()
    out_path = Path(args.output) if args.output else default_output_path()

    if not in_path.exists():
        print(f"[error] not found: {in_path}", file=sys.stderr)
        print(f"        pass a path argument, or put screenshots in {default_input_dir()}", file=sys.stderr)
        sys.exit(1)

    images = collect_images(in_path)
    if not images:
        print(f"[error] no images under: {in_path}", file=sys.stderr)
        sys.exit(1)
    print(f"[info] {len(images)} images to process")
    if args.crop_top:
        print(f"[info] cropping top {args.crop_top}px")

    try:
        from paddleocr import PaddleOCR
    except ImportError:
        print("[error] paddleocr not installed:", file=sys.stderr)
        print("        pip install paddlepaddle paddleocr", file=sys.stderr)
        sys.exit(1)

    print("[info] loading PaddleOCR (first run downloads models, ~30-60s)...")
    try:
        ocr = PaddleOCR(use_textline_orientation=True, lang=args.lang)
    except TypeError:
        ocr = PaddleOCR(use_angle_cls=True, lang=args.lang, show_log=False)

    all_msgs = []
    for i, img in enumerate(images, 1):
        print(f"[{i}/{len(images)}] {img.name}")
        items = process_image(ocr, img,
                              threshold_ratio=args.threshold,
                              center_band=args.center_band,
                              crop_top_px=args.crop_top,
                              debug=args.debug)
        all_msgs.extend(items)
        print(f"          -> {len(items)} chat lines")

    # 输出文本
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        for m in all_msgs:
            role = '本人' if m['role'] == 'self' else '对方'
            f.write(f"[{role}] {m['text']}\n")

    if args.json:
        json_path = out_path.with_suffix('.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            out_json = [
                {'role': m['role'], 'text': m['text'],
                 'y': m['y'], 'cx': m['cx']}
                for m in all_msgs
            ]
            json.dump(out_json, f, ensure_ascii=False, indent=2)
        print(f"[done] json: {json_path}")

    self_count = sum(1 for m in all_msgs if m['role'] == 'self')
    other_count = sum(1 for m in all_msgs if m['role'] == 'other')
    print(f"\n[done] {len(all_msgs)} lines -> {out_path}")
    print(f"       self  : {self_count}")
    print(f"       other : {other_count}")
    print()
    print("Next step:")
    print("    python setup_memorial.py")


if __name__ == '__main__':
    main()