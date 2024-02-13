import argparse
import xml.etree.ElementTree as ET
from itertools import chain


class TTXFont:
    def __init__(self, ttx_file):
        self.ttx_file = ttx_file
        self.tree = ET.parse(self.ttx_file)
        self.font_root = self.tree.getroot()
        self.font_head = self.font_root.findall('cmap')[0].findall('cmap_format_12')[0]

    def get_glyphs(self, is_sw=True):
        for map in self.font_head.findall('map'):
            name = map.attrib["name"]
            if (is_sw and "SW" in name) or (not is_sw and "SW" not in name):
                yield name, map.attrib["code"]


class VTPGenerator:
    def __init__(self, font: TTXFont, groups, lookup_list):
        """
        Initializes VTPGenerator
        :param ttx_file: The path to the ttx file
        :param groups: an array of Group objects
        :param lookup_list: an array of Lookup objects
        """
        self.font = font
        self.lookup_list = lookup_list
        self.groups = groups

    def generate(self):
        """
        Generates the vtp using class methods.
        """
        self.print_glyph_defs_header()
        self.print_glyph_defs()
        self.create_script()
        self.print_groups()
        self.print_lookups()
        self.print_CMAP()

    def print_glyph_defs_header(self):
        """
        Prints the header glyphs.
        """
        print()
        print('DEF_GLYPH "glyph0" ID 0 TYPE BASE END_GLYPH')
        print('DEF_GLYPH "null" ID 1 TYPE BASE END_GLYPH')
        print('DEF_GLYPH "CR" ID 2 TYPE BASE END_GLYPH')

    def print_glyph_defs(self):
        """
        Prints glyph definitions using data from the ttx file
        """
        id = 3

        all_glyphs = chain(self.font.get_glyphs(is_sw=False), self.font.get_glyphs(is_sw=True))

        for name, code in all_glyphs:
            print(f'DEF_GLYPH "{name}" ID {id} UNICODE {int(code, 16)} TYPE BASE END_GLYPH')
            id += 1

    def create_script(self, script_name="New Script", tag="dflt"):
        """
        Creates the font script
        """
        print(f'DEF_SCRIPT NAME "{script_name}" TAG "{tag}"\n')
        self.create_language()
        print('END_SCRIPT')

    def create_language(self, lang_name="Default", tag="dflt"):
        """
        creates the language script.
        """
        print(f'DEF_LANGSYS NAME "{lang_name}" TAG "{tag}"\n')
        self.create_mark_positioning()
        print('END_LANGSYS')

    def create_mark_positioning(self, tag="mark"):
        print(f'DEF_FEATURE NAME "Mark Positioning" TAG "{tag}"')
        self.create_lookup_list()
        print('END_FEATURE')

    def create_lookup_list(self):
        lookups_str = ''
        for loookup in self.lookup_list:
            lookups_str = lookups_str + f' LOOKUP "{loookup.lookup_name}"'
        print(lookups_str)

    def print_groups(self):
        for group in self.groups:
            group.print_group()

    def print_lookups(self):
        for lookup in self.lookup_list:
            lookup.print_lookup()

    def print_CMAP(self):
        print('CMAP_FORMAT 0 3 4')
        print('CMAP_FORMAT 0 4 12')
        print('CMAP_FORMAT 1 0 0')
        print('CMAP_FORMAT 3 1 4')
        print('CMAP_FORMAT 3 10 12 END')


class Lookup():
    def __init__(self, lookup_name, glyphs, contexets):
        self.lookup_name = lookup_name
        self.glyphs = glyphs
        self.contexts = contexets
        self.dx = self.calculate_dx()
        self.dy = self.calculate_dy()

    def calculate_dx(self):
        number = int(self.contexts[0][2:])
        return -(750 - number)

    def calculate_dy(self):
        number = int(self.contexts[1][2:])
        return 750 - number

    def print_lookup(self):
        print(f'DEF_LOOKUP "{self.lookup_name}" PROCESS_BASE PROCESS_MARKS ALL DIRECTION LTR')
        print("\tIN_CONTEXT")
        for context in self.contexts:
            print(f'\t\tRIGHT GLYPH "{context}"')
        print("\tEND_CONTEXT")
        print("\tAS_POSITION")
        # TODO figure out if there is "ADJUST_CLASS" or "ADJUST_GROUP" to make this more efficient
        print(f'\t\tADJUST_SINGLE')
        for glyph in self.glyphs:
            print(f'\t\t\tGLYPH "{glyph}" BY POS DX {self.dx} DY {self.dy} END_POS')
        print("\t\tEND_ADJUST")
        print("\tEND_POSITION")


class GlyphGroup:
    def __init__(self, group_name, ranges):
        self.group_name = group_name
        self.ranges = ranges

    def print_group(self):
        print(f'DEF_GROUP "{self.group_name}"')
        print(f' ENUM RANGE "{self.ranges[0]}" TO "{self.ranges[1]}" END_ENUM')
        print("END_GROUP")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--ttx", help="Path to the input TTX font file")
    args = parser.parse_args()

    markers = GlyphGroup("Markers", ["SWA", "SWR"])
    numbers = GlyphGroup("Numbers", ["SW250", "SW749"])
    g1 = GlyphGroup("g1", ["S10000", "S1a045"])
    g2 = GlyphGroup("g2", ["S1a046", "S2862c"])
    g3 = GlyphGroup("g3", ["S2862d", "S38b07"])
    groups = [markers, numbers, g1, g2, g3]

    font = TTXFont(args.ttx)
    orthogonal_shifts = list(range(480, 550))  # TODO Should be 250 to 750 for the full range
    # x_y_pairs = [(x, y) for x in orthogonal_shifts for y in orthogonal_shifts]
    x_y_pairs = [(482, 483), (506, 500), (503, 520)]

    sw_glyphs = [name for name, _ in font.get_glyphs(is_sw=False) if len(name) > 5][:5]  # TODO Should be all the glyphs
    sw_glyphs.append("S26b02")
    sw_glyphs.append("S20310")
    sw_glyphs.append("S33100")

    # Complexity: O(n^2) where n is the number of orthogonal shifts
    lookups = [Lookup(f"p{i+1}", sw_glyphs, [f"SW{x}", f"SW{y}"])
               for i, (x, y) in enumerate(x_y_pairs)]

    vtp_gen = VTPGenerator(font, groups, lookups)
    vtp_gen.generate()
