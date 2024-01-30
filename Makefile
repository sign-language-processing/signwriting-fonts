# Remote fonts
fonts/SuttonSignWritingOneD.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingOneD.ttf

fonts/SuttonSignWritingLine.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/raw/master/src/font/SuttonSignWritingLine.ttf

fonts/SuttonSignWritingFill.ttf:
	wget -O $@ https://github.com/sutton-signwriting/font-ttf/blob/master/src/font/SuttonSignWritingFill.ttf

# Examples
assets/SuttonSignWritingOneD-example.png: fonts/SuttonSignWritingOneD.ttf
	hb-view fonts/SuttonSignWritingOneD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

assets/SuttonSignWritingTwoD-example.png: fonts/SuttonSignWritingTwoD.ttf
	hb-view fonts/SuttonSignWritingTwoD.ttf "𝠃𝤛𝤵񍉡𝣴𝣵񆄱𝤌𝤆񈠣𝤉𝤚" --output-file $@ --margin=100

# Build

# Create a Two Tone font from the original fonts
fonts/SuttonSignWritingTwoTone.ttf: fonts/SuttonSignWritingLine.ttf fonts/SuttonSignWritingFill.ttf fonts/SuttonSignWritingOneD.ttf
	# TODO create a two tone font
	cp fonts/SuttonSignWritingOneD.ttf $@

# Turning the original ttf font file into a ttx file in order to change it
fonts/SuttonSignWritingTwoTone.ttx: fonts/SuttonSignWritingTwoTone.ttf
	ttx -o $@ fonts/SuttonSignWritingTwoTone.ttf

# Correcting and changing the ttx file, second argument is proportion
fonts/SuttonSignWritingTwoToneModified.ttx: fonts/SuttonSignWritingTwoTone.ttx signwriting_fonts/modify_ttx.py
	python -m signwriting_fonts.modify_ttx --input fonts/SuttonSignWritingTwoTone.ttx --output $@

# Turning the ttx file into a TTF file
fonts/SuttonSignWritingTwoToneModified.ttf: fonts/SuttonSignWritingTwoToneModified.ttx
	ttx -o $@ fonts/SuttonSignWritingTwoToneModified.ttx

# Generating a vtp file for the font
fonts/SuttonSignWritingTwoD.vtp: fonts/SuttonSignWritingTwoToneModified.ttx signwriting_fonts/generate_vtp.py
	python -m signwriting_fonts.generate_vtp --ttx fonts/SuttonSignWritingTwoToneModified.ttx > $@

# Add a VTP file instructions to a TTF File
fonts/SuttonSignWritingTwoD.ttf: fonts/SuttonSignWritingTwoD.vtp fonts/SuttonSignWritingTwoToneModified.ttf
	volt2ttf -t fonts/SuttonSignWritingTwoD.vtp fonts/SuttonSignWritingTwoToneModified.ttf $@