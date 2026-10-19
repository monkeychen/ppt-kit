from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt

from pptkit.common.units import DEFAULT_SLIDE_HEIGHT_EMU, DEFAULT_SLIDE_WIDTH_EMU


class BBox(BaseModel):
    x: StrictInt = Field(ge=0, description="Left X in EMU")
    y: StrictInt = Field(ge=0, description="Top Y in EMU")
    width: StrictInt = Field(gt=0, description="Width in EMU")
    height: StrictInt = Field(gt=0, description="Height in EMU")


class TextStyle(BaseModel):
    font_family: str = "PingFang SC"
    font_size_pt: float = Field(gt=0)
    color_hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$", default="#000000")
    bold: bool = False
    italic: bool = False
    underline: bool = False


class TextRun(BaseModel):
    text: str
    style: TextStyle


class Paragraph(BaseModel):
    runs: list[TextRun]
    align: Literal["left", "center", "right", "justify"] = "left"
    line_spacing_pt: float | None = None
    space_after_pt: float = 0.0


class BaseElement(BaseModel):
    id: str
    bbox: BBox
    z_order: int = 0
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source: Literal["vector", "ocr", "vlm", "cv", "synthetic", "fallback"] = "vector"
    degraded: bool = False


class TextBoxElement(BaseElement):
    kind: Literal["textbox"] = "textbox"
    paragraphs: list[Paragraph]
    word_wrap: bool = True
    margin_left_emu: StrictInt = 0
    margin_right_emu: StrictInt = 0
    margin_top_emu: StrictInt = 0
    margin_bottom_emu: StrictInt = 0


class ShapeElement(BaseElement):
    kind: Literal["shape"] = "shape"
    shape_type: Literal["rect", "round_rect", "ellipse", "line", "right_arrow", "freeform"]
    fill_color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke_color_hex: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    stroke_width_emu: StrictInt = 0
    corner_radius_ratio: float = Field(default=0.0, ge=0.0, le=0.5)
    points_emu: list[tuple[StrictInt, StrictInt]] | None = None


class ImageElement(BaseElement):
    kind: Literal["image"] = "image"
    image_path: str


SlideElement = Annotated[
    TextBoxElement | ShapeElement | ImageElement,
    Field(discriminator="kind"),
]


class Background(BaseModel):
    fill_type: Literal["solid", "image"] = "solid"
    color_hex: str = Field(default="#FFFFFF", pattern=r"^#[0-9A-Fa-f]{6}$")
    image_path: str | None = None


class SlideIR(BaseModel):
    page_index: StrictInt = Field(ge=0)
    route: Literal["vector", "raster"]
    width_emu: StrictInt = DEFAULT_SLIDE_WIDTH_EMU
    height_emu: StrictInt = DEFAULT_SLIDE_HEIGHT_EMU
    background: Background = Field(default_factory=Background)
    elements: list[SlideElement] = Field(default_factory=list)


class PresentationIR(BaseModel):
    source_path: str
    width_emu: StrictInt = DEFAULT_SLIDE_WIDTH_EMU
    height_emu: StrictInt = DEFAULT_SLIDE_HEIGHT_EMU
    slides: list[SlideIR] = Field(default_factory=list)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> "PresentationIR":
        return cls.model_validate_json(data)
