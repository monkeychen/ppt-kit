from pathlib import Path

import numpy as np
from PIL import Image

from pptkit.common.color import hex_to_rgb
from pptkit.ir.models import (
    Background,
    ImageElement,
    ShapeElement,
    SlideElement,
    SlideIR,
    SlideMaster,
    TextBoxElement,
)


def _compute_slide_bg_thumb(slide: SlideIR) -> np.ndarray:
    """Compute a 32x18 normalized RGB thumbnail for background comparison."""
    if slide.background.fill_type == "image" and slide.background.image_path:
        p = Path(slide.background.image_path)
        if p.exists():
            try:
                with Image.open(p) as img:
                    rgb = img.convert("RGB").resize((32, 18), Image.Resampling.BILINEAR)
                    return np.asarray(rgb, dtype=np.float32) / 255.0
            except Exception:
                pass

    # Solid fallback color
    r, g, b = hex_to_rgb(slide.background.color_hex or "#FFFFFF")
    arr = np.zeros((18, 32, 3), dtype=np.float32)
    arr[:, :, 0] = r / 255.0
    arr[:, :, 1] = g / 255.0
    arr[:, :, 2] = b / 255.0
    return arr


def _compute_bg_similarity(thumb_a: np.ndarray, thumb_b: np.ndarray) -> float:
    diff = np.mean(np.abs(thumb_a - thumb_b))
    return float(1.0 - diff)


def _elements_are_static_equivalent(
    e1: SlideElement,
    e2: SlideElement,
    tol_emu: int = 50000,
) -> bool:
    """Check if two elements across different slides are equivalent static master candidates."""
    if e1.kind != e2.kind:
        return False

    b1, b2 = e1.bbox, e2.bbox
    if (
        abs(b1.x - b2.x) > tol_emu
        or abs(b1.y - b2.y) > tol_emu
        or abs(b1.width - b2.width) > tol_emu
        or abs(b1.height - b2.height) > tol_emu
    ):
        return False

    if isinstance(e1, ShapeElement) and isinstance(e2, ShapeElement):
        return (
            e1.shape_type == e2.shape_type
            and e1.fill_color_hex == e2.fill_color_hex
            and e1.stroke_color_hex == e2.stroke_color_hex
        )

    if isinstance(e1, ImageElement) and isinstance(e2, ImageElement):
        # Same image filename or same relative position
        return Path(e1.image_path).name == Path(e2.image_path).name

    if isinstance(e1, TextBoxElement) and isinstance(e2, TextBoxElement):
        t1 = "".join(r.text for p in e1.paragraphs for r in p.runs).strip()
        t2 = "".join(r.text for p in e2.paragraphs for r in p.runs).strip()
        return t1 == t2

    return False


def induct_slide_masters(
    slides: list[SlideIR],
    similarity_threshold: float = 0.88,
) -> tuple[list[SlideMaster], list[SlideIR]]:
    """Cluster multi-slide backgrounds into title/content masters
    and extract common elements (F33)."""
    if not slides:
        return [], []

    # Deep copy slides to avoid mutating originals
    new_slides = [s.model_copy(deep=True) for s in slides]
    n = len(new_slides)
    if n == 1:
        master = SlideMaster(
            id="master-title",
            kind="title",
            background=new_slides[0].background,
        )
        new_slides[0].master_id = master.id
        return [master], new_slides

    # 1. Compute thumbnail embeddings for all backgrounds
    thumbs = [_compute_slide_bg_thumb(s) for s in new_slides]

    # 2. Cluster backgrounds by similarity
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j

    for i in range(n):
        for j in range(i + 1, n):
            if _compute_bg_similarity(thumbs[i], thumbs[j]) >= similarity_threshold:
                union(i, j)

    cluster_map: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        cluster_map.setdefault(root, []).append(i)

    # 3. Determine Title vs Content Master
    # If there are >= 2 clusters:
    # - The cluster containing slide 0 is Title Master if len(cluster_map[0]) < n * 0.7
    # - The largest other cluster is Content Master
    root_0 = find(0)
    has_distinct_cover = len(cluster_map[root_0]) < n and 0 in cluster_map[root_0]

    masters: list[SlideMaster] = []
    cluster_master_ids: dict[int, str] = {}

    if has_distinct_cover:
        title_root = root_0
        title_master = SlideMaster(
            id="master-title",
            kind="title",
            background=new_slides[0].background,
        )
        masters.append(title_master)
        cluster_master_ids[title_root] = title_master.id

        content_root = next(r for r in cluster_map if r != title_root)
        content_rep_idx = cluster_map[content_root][0]
        content_master = SlideMaster(
            id="master-content",
            kind="content",
            background=new_slides[content_rep_idx].background,
        )
        masters.append(content_master)
        cluster_master_ids[content_root] = content_master.id
    else:
        # All slides or majority share background
        content_master = SlideMaster(
            id="master-content",
            kind="content",
            background=new_slides[0].background,
        )
        masters.append(content_master)
        for r in cluster_map:
            cluster_master_ids[r] = content_master.id

    # Assign master_id and share background image path
    for r, s_indices in cluster_map.items():
        m_id = cluster_master_ids.get(r, masters[-1].id)
        m = next(m for m in masters if m.id == m_id)
        for idx in s_indices:
            new_slides[idx].master_id = m_id
            if m.background.fill_type == "image" and m.background.image_path:
                new_slides[idx].background = Background(
                    fill_type="image",
                    color_hex=m.background.color_hex,
                    image_path=m.background.image_path,
                )

    # 4. Extract cross-slide static elements to Content Master (AC33.2)
    for m in masters:
        if m.kind != "content":
            continue
        c_slide_indices = [i for i, s in enumerate(new_slides) if s.master_id == m.id]
        if len(c_slide_indices) < 2:
            continue

        c_slides = [new_slides[i] for i in c_slide_indices]
        ref_slide = c_slides[0]

        extracted_static: list[SlideElement] = []
        elem_ids_to_remove: set[str] = set()

        for cand_elem in ref_slide.elements:
            # Check if cand_elem is present in all other slides in this cluster
            all_present = True
            matched_ids = [cand_elem.id]

            for other_s in c_slides[1:]:
                found = None
                for other_e in other_s.elements:
                    if _elements_are_static_equivalent(cand_elem, other_e):
                        found = other_e
                        break
                if found is not None:
                    matched_ids.append(found.id)
                else:
                    all_present = False
                    break

            if all_present:
                # Candidate is static! Promote to master
                master_elem = cand_elem.model_copy(deep=True)
                master_elem.id = f"{m.id}-static-{len(extracted_static) + 1:02d}"
                extracted_static.append(master_elem)
                elem_ids_to_remove.update(matched_ids)

        if extracted_static:
            m.static_elements.extend(extracted_static)
            # Remove from each slide
            for s in c_slides:
                s.elements = [e for e in s.elements if e.id not in elem_ids_to_remove]

    return masters, new_slides
