from collections.abc import Callable

from pptkit.ir.models import SlideIR, TextBoxElement


def _apply_font_delta(slide_ir: SlideIR, delta_pt: float) -> tuple[SlideIR, bool]:
    trial_ir = slide_ir.model_copy(deep=True)
    changed = False
    for elem in trial_ir.elements:
        if isinstance(elem, TextBoxElement):
            for para in elem.paragraphs:
                for run in para.runs:
                    new_pt = max(6.0, round((run.style.font_size_pt + delta_pt) * 2.0) / 2.0)
                    if new_pt != run.style.font_size_pt:
                        run.style.font_size_pt = new_pt
                        changed = True
    return trial_ir, changed


def refine_slide_textboxes(
    slide_ir: SlideIR,
    eval_ssim_fn: Callable[[SlideIR], float],
    max_iter: int = 3,
) -> tuple[SlideIR, float, int]:
    best_ir = slide_ir.model_copy(deep=True)
    best_ssim = eval_ssim_fn(best_ir)
    if max_iter <= 0:
        return best_ir, best_ssim, 0

    iters_run = 0
    direction = 1.0
    step_size = 1.0

    for _ in range(max_iter):
        iters_run += 1
        delta_pt = direction * step_size
        trial_ir, changed = _apply_font_delta(best_ir, delta_pt)
        if not changed:
            break

        trial_ssim = eval_ssim_fn(trial_ir)
        if trial_ssim >= best_ssim:
            best_ssim = trial_ssim
            best_ir = trial_ir
        else:
            # Flip search direction and halve step size on the next iteration
            direction = -direction
            step_size = max(0.5, step_size * 0.5)

    return best_ir, best_ssim, iters_run
