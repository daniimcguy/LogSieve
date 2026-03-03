# main.py
import argparse
from logfilter_gui import LogFilterGUI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-InputFile", "--input-file", required=True, help="Path to input file")
    args = ap.parse_args()

    app = LogFilterGUI(args.input_file)
    app.mainloop()


if __name__ == "__main__":
    main()
