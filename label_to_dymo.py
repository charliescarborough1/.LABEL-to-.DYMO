#!/usr/bin/env python3
"""
label_to_dymo.py - Batch convert DYMO Label v8 (.label) files to
DYMO Connect (.dymo) format.

USAGE
    python label_to_dymo.py <input_folder> [output_folder]

    Input folder is searched recursively. Folder structure is mirrored
    in the output folder. Originals are never modified.

    python3 label_to_dymo.py ~/Desktop/Labels
    python3 label_to_dymo.py ~/Desktop/Labels ~/Desktop/Converted

    Override a stock's Connect name for the whole run:
    python3 label_to_dymo.py ~/Desktop/Labels --map 30323=LargeShipping30323

    Rewrite the address line for one or all store locations. Output goes
    into a subfolder per location (CV/, KT/, GT/):
    python3 label_to_dymo.py ~/Desktop/Labels --location GT
    python3 label_to_dymo.py ~/Desktop/Labels --location all

A report is written to <output_folder>\\_conversion_report.txt listing
every file converted, skipped, or failed.

If a label stock is not in STOCK_MAP below, the file is still converted
using a best-guess name and flagged in the report.
"""

import os
import sys
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

TWIPS = 1440.0
MIN_H = 0.125          # DYMO Connect minimum object height (inches)
DEFAULT_FONT = "Arial"

# ---------------------------------------------------------------------------
# Label stock map: v8 <PaperName>  ->  (Connect LabelName, width", height")
# Dimensions are the LONG side first (landscape). Add rows as needed.
# "confirmed" means verified against a known-good .dymo file.
# ---------------------------------------------------------------------------
STOCK_MAP = {
    "30336": ("Small30336",        2.125,  1.0),     # confirmed
    "30323": ("Shipping",          3.9688, 2.125),   # confirmed
    "30256": ("Shipping30256",     4.0,    2.3125),  # unconfirmed
    "30252": ("Address30252",      3.5,    1.125),   # unconfirmed
    "30321": ("LargeAddress30321", 3.5,    1.4),     # unconfirmed
}

# Command-line overrides, e.g.  --map 30323=LargeShipping30323
OVERRIDES = {}

# ---------------------------------------------------------------------------
# Store locations. --location CV|KT|GT|all rewrites the address line.
# Format is: street/city/state/zip, phone, website - padded into one line.
# ---------------------------------------------------------------------------
LOCATIONS = {
    "CV": ("199 N Main St., Centerville, OH 45459",
           "937-303-7621", "www.whitsfrozencustard.com"),
    "KT": ("424 E Stroop Rd., Kettering, OH 45429",
           "937-303-7577", "www.whitsfrozencustard.com"),
    "GT": ("2367 Dayton Germantown Pike, Germantown, OH 45327",
           "937-303-7802", "www.whitsfrozencustard.com"),
}

# Total character width of the assembled address line. The Centerville
# original is 102; keeping every location near this holds the spacing
# roughly consistent once AlwaysFit scales the text.
ADDRESS_WIDTH = 102


def address_line(code):
    """Assemble one padded address line for a location code."""
    addr, phone, site = LOCATIONS[code]
    content = len(addr) + len(phone) + len(site)
    pad = max(ADDRESS_WIDTH - content, 6)
    left = pad // 2
    right = pad - left
    return f"{addr}{' ' * left}{phone}{' ' * right}{site}"

# Object types this script understands. Anything else gets reported.
KNOWN = {"ImageObject", "TextObject", "AddressObject", "ShapeObject"}

# Every Whit's label carries a horizontal black bar under the flavor name.
# Some source .label files have no <ShapeObject> at all, so one is injected
# at the standard template position when the source is missing it.
ADD_MISSING_LINE = True
DEFAULT_LINE = (0.23333333, 0.67, 3.6000001, 0.1, 1.5)  # x, y, w, h, stroke pt


def make_default_line_object():
    x, y, w, h, stroke = DEFAULT_LINE
    return f"""        <LineObject>
          <Name>LINE</Name>
{brushes()}
{COMMON}
          <StrokeWidth>{n(stroke)}</StrokeWidth>
          <DashPattern>SolidLine</DashPattern>
          <LineType>Horizontal</LineType>
          <ObjectLayout>
            <DYMOPoint>
              <X>{n(x)}</X>
              <Y>{n(y)}</Y>
            </DYMOPoint>
            <Size>
              <Width>{n(w)}</Width>
              <Height>{n(h)}</Height>
            </Size>
          </ObjectLayout>
        </LineObject>"""


def n(v):
    return f"{float(v):.7g}"


def brushes(fill_white=False):
    fill = ('<Color A="0" R="1" G="1" B="1"></Color>' if fill_white
            else '<Color A="0" R="0" G="0" B="0"></Color>')
    return f"""          <Brushes>
            <BackgroundBrush>
              <SolidColorBrush>
                <Color A="0" R="1" G="1" B="1"></Color>
              </SolidColorBrush>
            </BackgroundBrush>
            <BorderBrush>
              <SolidColorBrush>
                <Color A="1" R="0" G="0" B="0"></Color>
              </SolidColorBrush>
            </BorderBrush>
            <StrokeBrush>
              <SolidColorBrush>
                <Color A="1" R="0" G="0" B="0"></Color>
              </SolidColorBrush>
            </StrokeBrush>
            <FillBrush>
              <SolidColorBrush>
                {fill}
              </SolidColorBrush>
            </FillBrush>
          </Brushes>"""


COMMON = """          <Rotation>Rotation0</Rotation>
          <OutlineThickness>1</OutlineThickness>
          <IsOutlined>False</IsOutlined>
          <BorderStyle>SolidLine</BorderStyle>
          <Margin>
            <DYMOThickness Left="0" Top="0" Right="0" Bottom="0" />
          </Margin>"""


def layout(bounds, label_h):
    x = float(bounds.get("X")) / TWIPS
    y = float(bounds.get("Y")) / TWIPS
    w = float(bounds.get("Width")) / TWIPS
    h = max(float(bounds.get("Height")) / TWIPS, MIN_H)
    if y + h > label_h:
        y = max(0.0, label_h - h)
    return f"""          <ObjectLayout>
            <DYMOPoint>
              <X>{n(x)}</X>
              <Y>{n(y)}</Y>
            </DYMOPoint>
            <Size>
              <Width>{n(w)}</Width>
              <Height>{n(h)}</Height>
            </Size>
          </ObjectLayout>"""


def get_runs(styled):
    out = []
    if styled is None:
        return out
    for el in styled.findall("Element"):
        fnt = el.find("Attributes/Font")
        if fnt is None:
            attrs = {"name": DEFAULT_FONT, "size": "12", "bold": "False",
                     "italic": "False", "underline": "False"}
        else:
            attrs = {
                "name": fnt.get("Family", DEFAULT_FONT),
                "size": fnt.get("Size", "12"),
                "bold": fnt.get("Bold", "False"),
                "italic": fnt.get("Italic", "False"),
                "underline": fnt.get("Underline", "False"),
            }
        out.append((el.findtext("String") or "", attrs))
    return out


def formatted(runs, fit, ha, va):
    """One <LineTextSpan> per visual line; split runs on embedded newlines."""
    lines, cur = [], []
    for txt, fnt in runs:
        for i, part in enumerate(txt.replace("\r\n", "\n").split("\n")):
            if i:
                lines.append(cur)
                cur = []
            if part:
                cur.append((part, fnt))
    lines.append(cur)
    lines = [ln for ln in lines if ln]
    if not lines:
        lines = [[("", {"name": DEFAULT_FONT, "size": "12", "bold": "False",
                        "italic": "False", "underline": "False"})]]

    s = ["          <FormattedText>",
         f"            <FitMode>{fit}</FitMode>",
         f"            <HorizontalAlignment>{ha}</HorizontalAlignment>",
         f"            <VerticalAlignment>{va}</VerticalAlignment>",
         "            <IsVertical>False</IsVertical>"]
    for ln in lines:
        s.append("            <LineTextSpan>")
        for txt, f in ln:
            s += ["              <TextSpan>",
                  f"                <Text>{escape(txt)}</Text>",
                  "                <FontInfo>",
                  f"                  <FontName>{escape(f['name'])}</FontName>",
                  f"                  <FontSize>{f['size']}</FontSize>",
                  f"                  <IsBold>{f['bold']}</IsBold>",
                  f"                  <IsItalic>{f['italic']}</IsItalic>",
                  f"                  <IsUnderline>{f['underline']}</IsUnderline>",
                  "                  <FontBrush>",
                  "                    <SolidColorBrush>",
                  '                      <Color A="1" R="0" G="0" B="0"></Color>',
                  "                    </SolidColorBrush>",
                  "                  </FontBrush>",
                  "                </FontInfo>",
                  "              </TextSpan>"]
        s.append("            </LineTextSpan>")
    s.append("          </FormattedText>")
    return "\n".join(s)


def convert(src_path, location=None):
    """Returns (xml_string, list_of_warnings)."""
    warnings = []
    root = ET.parse(src_path).getroot()

    if root.tag != "DieCutLabel":
        raise ValueError(f"not a v8 label file (root tag is <{root.tag}>)")

    paper = (root.findtext("PaperName") or "").strip()
    orientation = (root.findtext("PaperOrientation") or "Landscape").strip()

    stock_no = "".join(c for c in paper if c.isdigit())[:5]

    if stock_no in OVERRIDES:
        label_name = OVERRIDES[stock_no]
        _, lw, lh = STOCK_MAP.get(stock_no, (None, 3.9688, 2.125))
    elif stock_no in STOCK_MAP:
        label_name, lw, lh = STOCK_MAP[stock_no]
    else:
        rect = root.find("DrawCommands/RoundRectangle")
        if rect is not None:
            a = float(rect.get("Width")) / TWIPS
            b = float(rect.get("Height")) / TWIPS
            lw, lh = max(a, b), min(a, b)
        else:
            lw, lh = 3.9688, 2.125
        label_name = f"Shipping{stock_no}" if stock_no else "Shipping30323"
        warnings.append(f"unmapped stock '{paper}' -> guessed '{label_name}' "
                        f"({lw:.4g} x {lh:.4g} in). Add it to STOCK_MAP or "
                        f"pass --map {stock_no}=CorrectName")

    if orientation == "Portrait":
        lw, lh = lh, lw

    objects = []
    for info in root.findall("ObjectInfo"):
        bounds = info.find("Bounds")
        kids = [c for c in info if c.tag != "Bounds"]
        if not kids or bounds is None:
            continue
        obj = kids[0]
        name = obj.findtext("Name") or obj.tag

        if obj.tag not in KNOWN:
            warnings.append(f"DROPPED unsupported object <{obj.tag}> "
                            f"named '{name}'")
            continue

        if obj.tag == "ImageObject":
            data = (obj.findtext("Image") or "").strip()
            if not data:
                warnings.append(f"image object '{name}' has no data")
            objects.append(f"""        <ImageObject>
          <Name>{escape(name)}</Name>
{brushes()}
{COMMON}
          <Data>{data}</Data>
          <ScaleMode>{obj.findtext('ScaleMode', 'Uniform')}</ScaleMode>
          <HorizontalAlignment>{obj.findtext('HorizontalAlignment', 'Left')}</HorizontalAlignment>
          <VerticalAlignment>{obj.findtext('VerticalAlignment', 'Top')}</VerticalAlignment>
{layout(bounds, lh)}
        </ImageObject>""")

        elif obj.tag == "ShapeObject":
            shape = obj.findtext("ShapeType", "HorizontalLine")
            if "Line" not in shape:
                warnings.append(f"DROPPED shape '{name}' of type "
                                f"{shape} (only lines are supported)")
                continue
            stroke = float(obj.findtext("LineWidth", "30")) / 20.0
            ltype = "Horizontal" if "Horizontal" in shape else "Vertical"
            objects.append(f"""        <LineObject>
          <Name>{escape(name)}</Name>
{brushes(fill_white=True)}
{COMMON}
          <StrokeWidth>{n(stroke)}</StrokeWidth>
          <DashPattern>SolidLine</DashPattern>
          <LineType>{ltype}</LineType>
{layout(bounds, lh)}
        </LineObject>""")

        else:  # TextObject / AddressObject
            if obj.tag == "AddressObject" and location:
                st = obj.find("StyledText")
                els = st.findall("Element") if st is not None else []
                if els:
                    for extra_el in els[1:]:
                        st.remove(extra_el)
                    els[0].find("String").text = address_line(location)
                else:
                    warnings.append("address object had no text to rewrite")
            ha = obj.findtext("HorizontalAlignment", "Left")
            va = obj.findtext("VerticalAlignment", "Top")
            fit = "AlwaysFit"
            extra = ("\n          <BarcodePosition>Top</BarcodePosition>"
                     if obj.tag == "AddressObject" else "")
            body = formatted(get_runs(obj.find("StyledText")), fit, ha, va)
            objects.append(f"""        <{obj.tag}>
          <Name>{escape(name)}</Name>
{brushes()}
{COMMON}
          <HorizontalAlignment>{ha}</HorizontalAlignment>
          <VerticalAlignment>{va}</VerticalAlignment>
          <FitMode>{fit}</FitMode>
          <IsVertical>False</IsVertical>
{body}{extra}
{layout(bounds, lh)}
        </{obj.tag}>""")

    if ADD_MISSING_LINE and not any("<LineObject>" in o for o in objects):
        objects.append(make_default_line_object())
        warnings.append("source had no black bar; standard line injected")

    if not objects:
        warnings.append("no convertible objects found")

    rect_x, rect_y = 0.09, 0.0567
    rect_w = max(lw - 0.1483, 0.1)
    rect_h = max(lh - 0.0967, 0.1)

    doc = f"""<?xml version="1.0" encoding="utf-8"?>
<DesktopLabel Version="1">
  <DYMOLabel Version="4">
    <Description>DYMO Label</Description>
    <Orientation>{orientation}</Orientation>
    <LabelName>{label_name}</LabelName>
    <InitialLength>0</InitialLength>
    <BorderStyle>SolidLine</BorderStyle>
    <DYMORect>
      <DYMOPoint>
        <X>{n(rect_x)}</X>
        <Y>{n(rect_y)}</Y>
      </DYMOPoint>
      <Size>
        <Width>{n(rect_w)}</Width>
        <Height>{n(rect_h)}</Height>
      </Size>
    </DYMORect>
    <BorderColor>
      <SolidColorBrush>
        <Color A="1" R="0" G="0" B="0"></Color>
      </SolidColorBrush>
    </BorderColor>
    <BorderThickness>1</BorderThickness>
    <Show_Border>False</Show_Border>
    <HasFixedLength>False</HasFixedLength>
    <FixedLengthValue>0</FixedLengthValue>
    <DynamicLayoutManager>
      <RotationBehavior>ClearObjects</RotationBehavior>
      <LabelObjects>
{chr(10).join(objects)}
      </LabelObjects>
    </DynamicLayoutManager>
  </DYMOLabel>
  <LabelApplication>Blank</LabelApplication>
  <DataTable>
    <Columns></Columns>
    <Rows></Rows>
  </DataTable>
</DesktopLabel>
"""
    ET.fromstring(doc.encode("utf-8"))  # sanity check: must parse
    return doc, warnings


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    args = []
    locations = [None]
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--location":
            val = argv[i + 1] if i + 1 < len(argv) else ""
            locations = list(LOCATIONS) if val.lower() == "all" \
                else [c.strip().upper() for c in val.split(",")]
            continue
        if i and argv[i - 1] == "--location":
            continue
        if a.startswith("--map"):
            continue
        if "=" in a and not os.path.exists(a):
            k, v = a.split("=", 1)
            OVERRIDES["".join(c for c in k if c.isdigit())[:5]] = v
        else:
            args.append(a)

    if not args:
        print(__doc__)
        sys.exit(1)

    in_dir = os.path.abspath(args[0])
    out_dir = os.path.abspath(args[1]) if len(args) > 1 \
        else in_dir + "_dymo"

    if OVERRIDES:
        print("Name overrides:", OVERRIDES)

    for code in locations:
        if code is None:
            continue
        if code not in LOCATIONS:
            print(f"ERROR: unknown location '{code}'. "
                  f"Known: {', '.join(LOCATIONS)}")
            sys.exit(1)
        if "GOES-HERE" in LOCATIONS[code][1]:
            print(f"ERROR: {code} still has a placeholder phone number. "
                  f"Edit LOCATIONS at the top of this script first.")
            sys.exit(1)
        print(f"  {code}: {address_line(code)}")

    if not os.path.isdir(in_dir):
        print(f"ERROR: not a folder: {in_dir}")
        sys.exit(1)

    todo = []
    for dirpath, _, files in os.walk(in_dir):
        for fn in files:
            if fn.lower().endswith(".label"):
                todo.append(os.path.join(dirpath, fn))
    todo.sort()

    if not todo:
        print(f"No .label files found under {in_dir}")
        sys.exit(1)

    print(f"Found {len(todo)} .label files")
    print(f"Writing to {out_dir}\n")

    ok, failed, flagged = 0, [], []
    for code in locations:
        base = out_dir if code is None else os.path.join(out_dir, code)
        if code:
            print(f"\n--- {code} ---")
        for i, src in enumerate(todo, 1):
            rel = os.path.relpath(src, in_dir)
            dst = os.path.join(base, os.path.splitext(rel)[0] + ".dymo")
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                doc, warns = convert(src, code)
                with open(dst, "w", encoding="utf-8-sig") as fh:
                    fh.write(doc)
                ok += 1
                if warns:
                    flagged.append((f"{code or ''}/{rel}", warns))
                status = "OK " if not warns else "OK*"
            except Exception as e:
                failed.append((f"{code or ''}/{rel}", f"{type(e).__name__}: {e}"))
                status = "FAIL"
            print(f"[{i:>4}/{len(todo)}] {status}  {rel}")

    report = os.path.join(out_dir, "_conversion_report.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(f"Source:    {in_dir}\n")
        fh.write(f"Output:    {out_dir}\n")
        fh.write(f"Locations: {', '.join(c or '(unchanged)' for c in locations)}\n")
        fh.write(f"Converted: {ok} of {len(todo) * len(locations)}\n")
        fh.write(f"Failed:    {len(failed)}\n")
        fh.write(f"Flagged:   {len(flagged)}\n\n")
        if failed:
            fh.write("=== FAILED ===\n")
            for rel, err in failed:
                fh.write(f"{rel}\n    {err}\n")
            fh.write("\n")
        if flagged:
            fh.write("=== CONVERTED WITH WARNINGS ===\n")
            for rel, warns in flagged:
                fh.write(f"{rel}\n")
                for w in warns:
                    fh.write(f"    {w}\n")
            fh.write("\n")
        stocks = {}
        for src in todo:
            try:
                p = (ET.parse(src).getroot().findtext("PaperName") or "?").strip()
            except Exception:
                p = "(unreadable)"
            stocks[p] = stocks.get(p, 0) + 1
        fh.write("=== LABEL STOCKS SEEN ===\n")
        for p, c in sorted(stocks.items(), key=lambda kv: -kv[1]):
            num = "".join(c for c in p if c.isdigit())[:5]
            mapped = "mapped" if (num in STOCK_MAP or num in OVERRIDES) \
                else "NOT MAPPED"
            fh.write(f"{c:>5}  {p}   [{mapped}]\n")

    print(f"\nDone. {ok} converted, {len(failed)} failed, "
          f"{len(flagged)} flagged.")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
