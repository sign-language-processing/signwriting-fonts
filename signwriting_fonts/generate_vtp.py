import argparse
import xml.etree.ElementTree as ET


class VTPGenerator:
    def __init__(self, ttx_file, groups, lookup_list):
        """
        Initializes VTPGenerator
        :param ttx_file: The path to the ttx file
        :param groups: an array of Group objects
        :param lookup_list: an array of Lookup objects
        """
        self.ttx_file = ttx_file
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
        tree = ET.parse(self.ttx_file)
        root = tree.getroot()
        # Getting the data from the ttx file
        head = root.findall('cmap')[0].findall('cmap_format_12')[0]
        id = 3
        for map in head.findall('map'):
            name = map.attrib["name"]
            if "SW" in name:
                continue
            else:
                code = map.attrib["code"]
                print(f'DEF_GLYPH "{name}" ID {id} UNICODE {int(code, 16)} TYPE BASE END_GLYPH')
                id += 1
        for map in head.findall('map'):
            name = map.attrib["name"]
            if name.__contains__("SW"):
                code = map.attrib["code"]
                print(f'DEF_GLYPH "{name}" ID {id} UNICODE {int(code, 16)} TYPE BASE END_GLYPH')
                id += 1

    def create_script(self, script_name="New Script", tag="dflt"):
        """
        Creates the font script
        """
        print(f'DEF_SCRIPT NAME "{script_name}" TAG "{tag}"\n')
        self.create_language()
        print(f'END_SCRIPT')

    def create_language(self, lang_name="Default", tag="dflt"):
        """
        creates the language script.
        """
        print(f'DEF_LANGSYS NAME "{lang_name}" TAG "{tag}"\n')
        self.create_mark_positioning()
        print(f'END_LANGSYS')

    def create_mark_positioning(self, tag="mark"):
        print(f'DEF_FEATURE NAME "Mark Positioning" TAG "{tag}"')
        self.create_lookup_list()
        print(f'END_FEATURE')

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
    def __init__(self, lookup_name, glyph, direction, contexets):
        self.lookup_name = lookup_name
        self.glyph = glyph
        self.direction = direction
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
        print("IN_CONTEXT")
        for context in self.contexts:
            print(f' RIGHT GLYPH "{context}"')
        print("END_CONTEXT")
        print("AS_POSITION")
        print(f'ADJUST_SINGLE GLYPH "{self.glyph}" BY POS DX {self.dx} DY {self.dy} END_POS')
        print("END_ADJUST")
        print("END_POSITION")


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
    g4 = GlyphGroup("g4", ["S10000", "S10010"])
    groups = [markers, numbers, g1, g2, g3, g4]
    # TODO apply this lookup to all groups
    p1 = Lookup("p1", "S26b02", "LTR", ["SW503", "SW520"])
    p2 = Lookup("p2", "S20310", "LTR", ["SW506", "SW500"])
    p3 = Lookup("p3", "S33100", "LTR", ["SW482", "SW483"])
    lookups = [p1, p2, p3]
    vtp_gen = VTPGenerator(args.ttx, groups, lookups)
    vtp_gen.generate()
