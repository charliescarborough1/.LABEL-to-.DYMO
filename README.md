# DYMO Label v8 to DYMO Connect Converter

`label_to_dymo.py` batch-converts DYMO Label v8 `.label` files to DYMO Connect `.dymo` files. It searches the input folder recursively, mirrors its folder structure in the output, and leaves the source labels untouched.

## Requirements

Python 3. The script uses the Python standard library and requires no package installation.

## Usage

From the folder containing the script, pass the folder that holds your source labels:

```sh
python3 label_to_dymo.py ./labels
```

The default output is a sibling folder with `_dymo` appended to the input folder name. For example, `labels/products/vanilla.label` becomes `labels_dymo/products/vanilla.dymo`.

To choose a different output folder, pass it as the second argument:

```sh
python3 label_to_dymo.py ./labels ./converted
```

Relative paths are resolved from your current working directory. The script creates output folders as needed and replaces existing `.dymo` files at the same destination when a conversion succeeds.

## Label stock and address options

Use `--map` to override the DYMO Connect label name for a stock number for the current run:

```sh
python3 label_to_dymo.py ./labels ./converted --map 30323=LargeShipping30323
```

If a stock has no mapping or override, the script guesses a name and flags it in the report. To add a permanent mapping with custom dimensions, edit `STOCK_MAP` in the script.

Use `--location` to replace the text of address objects with a preset from `LOCATIONS`. Each location gets its own output subfolder. Omit the option to keep the original address text.

```sh
python3 label_to_dymo.py ./labels ./converted --location GT
python3 label_to_dymo.py ./labels ./converted --location CV,KT
python3 label_to_dymo.py ./labels ./converted --location all
```

## Review the results

Open `_conversion_report.txt` in the output folder for conversion totals, errors, warnings, and a list of the stocks found. The report includes the resolved absolute input and output paths.

The script supports embedded images, text, address objects, and line shapes. It drops unsupported object types and non-line shapes and records them in the report. By default, it adds a horizontal line at a fixed template position when no line was converted. Set `ADD_MISSING_LINE = False` in the script to disable that behavior.

Open a converted label in DYMO Connect to check the stock, layout, and appearance before printing.
