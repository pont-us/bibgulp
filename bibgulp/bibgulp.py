#!/usr/bin/env python3

# MIT License
#
# Copyright (c) 2020-2021 Pontus Lurcock
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""bibgulp: prettify downloaded BibTeX records and put them on the clipboard

See readme for details.
"""

import argparse
import os
import re
import subprocess
import textwrap
import time
import unicodedata
from typing import Union

from bibtexparser import customization as czn
from bibtexparser.bparser import BibTexParser
from bibtexparser.latexenc import string_to_latex


def main():
    parser = argparse.ArgumentParser(description="Reformat bibtex files.")
    parser.add_argument("inputfile", metavar="filename", type=str, nargs="?",
                        help="input file, or directory to watch")
    args = parser.parse_args()
    if os.path.isdir(args.inputfile):
        watch_dir(args.inputfile)
    else:
        parse_file(args.inputfile)


_stop_words = "a an the on is it at of in as to are there el la has"
stop_words = set(_stop_words.split())
field_order = """author title year journal volume number pages
                 editor booktitle series keywords""".split()
known_fields = set(field_order + ["ENTRYTYPE", "ID", "abstract"])
capitalizers = {"Science", "Geology", "Surveys in Geophysics", "Radiocarbon"}


def get_first_word(record):
    if "title" not in record:
        return
    title = record["title"]
    words = [w.lower() for w in title.split()]
    for word in words:
        if word not in stop_words and \
           not re.match(r"\d", word):
            return word
    return "xxx"


def fix_pages(record):
    if "pages" not in record:
        return
    p0 = record["pages"]
    matches = re.search(r"(\d+)\D+(\d+)", p0)
    if matches:
        record["pages"] = "%s--%s" % (matches.group(1), matches.group(2))


def fix_title(record):
    if "title" not in record:
        return
    if "journal" in record and record["journal"] in capitalizers:
        return
    words = record["title"].split(" ")
    for i in range(1, len(words)):
        word0 = words[i]
        if len(word0) > 1 and word0[0].isupper() and word0[1:].islower():
            # title case
            word1 = "{"+word0[0]+"}"+word0[1:]
        elif word0.islower() or not re.match(r"[a-zA-Z]", word0):
            # all lowercase, or no alphabetic characters
            word1 = word0
        else:  # mixed case or all upper case
            word1 = "{" + word0 + "}"
        words[i] = word1
    record["title"] = " ".join(words)


def print_field(output, key, value):
    line = "%s = {%s}," % (key, value)
    wrapper = textwrap.TextWrapper(width=78,
                                   initial_indent="  ",
                                   subsequent_indent="    ")
    lines = wrapper.wrap(line)
    output += lines


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize('NFD', s)
                   if unicodedata.category(c) != 'Mn')


def clean_record(record):
    id_ = record["ID"]
    if len(id_) > 0 and id_[0] == "\n" and "=" in id_:
        # probably a blank ID which has swallowed the first field
        parts = id_[1:].split("=")
        record[parts[0]] = parts[1][1:]
    for key, value in record.items():
        record[key] = value.strip()
    czn.author(record)  # modifies in-place
    fix_pages(record)
    if "abstract" not in record:
        record["abstract"] = ""
    if "author" not in record:
        record["author"] = ["Anonymous"]
    if "link" in record:
        record["url"] = record["link"]
        del record["link"]
    if "keyword" in record:
        record["keywords"] = record["keyword"]
        del record["keyword"]
    if "keywords" in record:
        kw = record["keywords"]
        kw = kw.lower()
        if "," in kw and ";" not in kw:
            kw = kw.replace(",", ";")
        if ";" in kw and "; " not in kw:
            kw = kw.replace(";", "; ")
        record["keywords"] = kw
    if "note" in record and record["note"] == "":
        del record["note"]
    if "year" not in record:
        record["year"] = "XXXX"
    if "number" in record:
        record["number"] = record["number"].replace("–", "--")
    authorkey = strip_accents(record["author"][0].split(",")[0].lower())
    output = ["@%s{%s%s%s," % (record["ENTRYTYPE"], authorkey, record["year"],
                               get_first_word(record))]
    record["author"] = " and ".join(record["author"])
    record["author"] = string_to_latex(record["author"])
    fix_title(record)
    if "doi" in record:
        # Elsevier don't know the difference between a DOI and a URL.
        # record["doi"] = record["doi"].replace("http://dx.doi.org/", "")
        record["doi"] = re.sub("^https?://(dx.)?doi.org/", "", record["doi"])
    for field in field_order:
        if field in record:
            print_field(output, field, record[field])
    for key, value in record.items():
        if key not in known_fields:
            print_field(output, key, value)

    # Elsevier like to throw in some backslashes and curly brackets.
    record["abstract"] = \
        record["abstract"].replace(r"\{", "").replace(r"\}", "")

    if "url" in record and "sciencedirect" in record["url"]:
        # Elsevier append the word "Abstract" to the start of the abstract.
        record["abstract"] = re.sub("^Abstract ", "", record["abstract"])
    print_field(output, "abstract", record["abstract"])
    output[-1] = output[-1][:-1]  # strip trailing comma
    output.append("}")
    return "\n".join(output)+"\n\n"


def parse_bibtex(contents: Union[str, bytes]) -> None:
    # common_strings: see
    # https://bibtexparser.readthedocs.io/en/master/bibtexparser.html#module-bibtexparser.bparser
    # and https://github.com/sciunto-org/python-bibtexparser/issues/248 .
    parser = BibTexParser(common_strings=True)
    contents_str = \
        contents if type(contents) == str else contents.decode('utf-8')
    database = parser.parse(contents_str + "\n")
    for record in database.entries:
        output = clean_record(record)
        print(output)
        to_clipboard(output)


def parse_file(filename: str) -> None:
    ris = False
    with open(filename, "r") as bibfile:
        for i in range(10):
            line = bibfile.readline()
            if line.startswith("TY  - "):
                ris = True
    if ris:
        process = subprocess.run(
            ["ris2xml \"%s\" | xml2bib" % filename],
            shell=True, capture_output=True)
        parse_bibtex(process.stdout)
    else:
        with open(filename, "r") as bibfile:
            parse_bibtex(bibfile.read())


def to_clipboard(text: str) -> None:
    for options in "-pi", "-bi":
        p = subprocess.Popen(["xsel", options], stdin=subprocess.PIPE)
        p.communicate(input=bytes(text, "UTF-8"))


def watch_dir(dirname: str) -> None:
    contents_prev = set(os.listdir(dirname))
    while True:
        time.sleep(0.2)
        contents = set(os.listdir(dirname))
        contents_new = contents - contents_prev
        time.sleep(0.3)  # let partial files finish downloading
        for leafname in contents_new:
            if re.search(r"[.](pdf|part|crdownload)$", leafname, re.IGNORECASE):
                continue
            print("Parsing: ", leafname)
            parse_file(os.path.join(dirname, leafname))
        contents_prev = contents


if __name__ == "__main__":
    main()
