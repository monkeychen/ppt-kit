from dataclasses import dataclass

from pptkit.common.color import compute_delta_e
from pptkit.ir.models import BBox, ShapeElement, SlideIR, TextBoxElement


@dataclass
class SlideEvalMetrics:
    char_accuracy: float
    textbox_iou: float
    font_size_mae_pt: float
    color_delta_e: float
    shape_recall: float
    shape_precision: float
    ssim: float


def compute_bbox_iou(a: BBox, b: BBox) -> float:
    ax1, ay1 = a.x + a.width, a.y + a.height
    bx1, by1 = b.x + b.width, b.y + b.height

    ix0, iy0 = max(a.x, b.x), max(a.y, b.y)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)

    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0

    inter = float((ix1 - ix0) * (iy1 - iy0))
    union = float(a.width * a.height + b.width * b.height) - inter
    return inter / union if union > 0 else 0.0


def _levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _extract_textbox_text(tb: TextBoxElement) -> str:
    return "\n".join("".join(r.text for r in p.runs) for p in tb.paragraphs)


def evaluate_slide_ir(pred: SlideIR, gt: SlideIR, ssim: float = 1.0) -> SlideEvalMetrics:
    pred_tbs = [e for e in pred.elements if isinstance(e, TextBoxElement)]
    gt_tbs = [e for e in gt.elements if isinstance(e, TextBoxElement)]

    # 1. Character accuracy across concatenated textboxes
    pred_all_text = "\n".join(_extract_textbox_text(t) for t in pred_tbs)
    gt_all_text = "\n".join(_extract_textbox_text(t) for t in gt_tbs)
    if not gt_all_text and not pred_all_text:
        char_acc = 1.0
    elif not gt_all_text:
        char_acc = 0.0
    else:
        dist = _levenshtein(pred_all_text, gt_all_text)
        char_acc = max(0.0, 1.0 - dist / max(len(gt_all_text), 1))

    # 2. Match textboxes by greedy max IoU
    ious: list[float] = []
    size_errs: list[float] = []
    color_errs: list[float] = []
    used_pred_tb: set[int] = set()

    for gt_tb in gt_tbs:
        best_iou = 0.0
        best_idx = -1
        for idx, p_tb in enumerate(pred_tbs):
            if idx in used_pred_tb:
                continue
            iou = compute_bbox_iou(gt_tb.bbox, p_tb.bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = idx
        ious.append(best_iou)
        if best_idx >= 0:
            used_pred_tb.add(best_idx)
            matched_tb = pred_tbs[best_idx]
            gt_runs = [r for p in gt_tb.paragraphs for r in p.runs]
            pr_runs = [r for p in matched_tb.paragraphs for r in p.runs]
            if gt_runs and pr_runs:
                size_errs.append(abs(gt_runs[0].style.font_size_pt - pr_runs[0].style.font_size_pt))
                color_errs.append(
                    compute_delta_e(gt_runs[0].style.color_hex, pr_runs[0].style.color_hex)
                )

    avg_tb_iou = sum(ious) / len(ious) if ious else 1.0
    avg_size_err = sum(size_errs) / len(size_errs) if size_errs else 0.0
    avg_color_de = sum(color_errs) / len(color_errs) if color_errs else 0.0

    # 3. Shape recall and precision
    pred_shapes = [e for e in pred.elements if isinstance(e, ShapeElement)]
    gt_shapes = [e for e in gt.elements if isinstance(e, ShapeElement)]
    used_pred_sh: set[int] = set()
    matched_shapes = 0

    for gt_sh in gt_shapes:
        for idx, p_sh in enumerate(pred_shapes):
            if idx in used_pred_sh:
                continue
            if (
                p_sh.shape_type == gt_sh.shape_type
                and compute_bbox_iou(gt_sh.bbox, p_sh.bbox) >= 0.5
            ):
                used_pred_sh.add(idx)
                matched_shapes += 1
                break

    shape_recall = matched_shapes / len(gt_shapes) if gt_shapes else 1.0
    shape_precision = matched_shapes / len(pred_shapes) if pred_shapes else 1.0

    return SlideEvalMetrics(
        char_accuracy=char_acc,
        textbox_iou=avg_tb_iou,
        font_size_mae_pt=avg_size_err,
        color_delta_e=avg_color_de,
        shape_recall=shape_recall,
        shape_precision=shape_precision,
        ssim=ssim,
    )
