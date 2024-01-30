import argparse
import re
from pathlib import Path
from xml.etree import ElementTree


def is_number_glyf(name):
    if 'SW2' in name or 'SW3' in name or 'SW4' in name or 'SW5' in name or 'SW6' in name or 'SW7' in name:
        return True
    else:
        return False


def correct_glyph_names(font_xml: str):
    # Since SuttonSignWritingOneD doesn't follow naming conventions, we need to correct the names.
    # The names include whitespaces and those are not welcome in various platforms such as VOLT
    return font_xml.replace('"SW ', '"SW')


def resize_boxes(font_xml: str):
    # Setting the width of the boxes to 500
    return font_xml.replace('name="SWM" width="0"', 'name="SWM" width="500"')


def replace_box_glyphs(font_xml: str):
    # Making the MBox into a 500x500 svg

    new_glyph_path = Path(__file__).parent / "boxes/M.xml"
    with open(new_glyph_path, "r") as glyph_file:
        new_glyph = glyph_file.read()

    return re.sub(r'<TTGlyph name=\"SWM\"[\s\S]*?<\/TTGlyph>', new_glyph, font_xml)


def remove_number_glyphs(root: ElementTree.XML):
    # If it is a number glyph then we remove all the contours
    head = root.findall('glyf')
    for glyf in head[0].findall('TTGlyph'):
        if is_number_glyf(glyf.attrib["name"]):
            for contour in glyf.findall("contour"):
                glyf.remove(contour)


def resize_all_glyphs(root: ElementTree.XML, scale=0.09):
    # TODO: unclear why this is needed

    head = root.findall('glyf')
    for glyf in head[0].findall('TTGlyph'):
        if (is_number_glyf(glyf.attrib["name"]) or
                glyf.attrib["name"] in ["SWM", ".notdef", ".null", "nonmarkingreturn"]):
            continue

        x_min = float(glyf.attrib['xMin'])
        x_max = float(glyf.attrib['xMax'])
        y_min = float(glyf.attrib['yMin'])
        y_max = float(glyf.attrib['yMax'])
        dx = float((x_max - x_min) / 2)
        dy = float((y_max - y_min) / 2)
        glyf.attrib['xMin'] = str((x_min - dx) * scale)
        glyf.attrib['xMax'] = str((x_max - dx) * scale)
        glyf.attrib['yMin'] = str((y_min - dy) * scale)
        glyf.attrib['yMax'] = str((y_max - dy) * scale)
        for contour in glyf.findall("contour"):
            for point in contour.findall("pt"):
                point.attrib['x'] = str((float(point.attrib['x']) - dx) * scale)
                point.attrib['y'] = str((float(point.attrib['y']) - dy) * scale)


def rebox_all_glyphs(root: ElementTree.XML):
    for mtx in root.findall('hmtx')[0]:
        if mtx.attrib["name"] == "SWM":
            mtx.attrib['width'] = "500"
        else:
            # Setting the width of all the glyphs to 0
            mtx.attrib['width'] = "0"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="Path to the input TTX font file")
    parser.add_argument("--output", help="Path to the output TTX font file")
    args = parser.parse_args()

    with open(args.input, "r") as f:
        font_xml = f.read()

    font_xml = correct_glyph_names(font_xml)
    font_xml = resize_boxes(font_xml)
    font_xml = replace_box_glyphs(font_xml)

    # Changing the TTX file by parsing and modifying it
    root = ElementTree.XML(font_xml)
    remove_number_glyphs(root)
    rebox_all_glyphs(root)
    resize_all_glyphs(root)

    with open(args.output, "wb") as f:
        f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(ElementTree.tostring(root))


if __name__ == "__main__":
    main()
