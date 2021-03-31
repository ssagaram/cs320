import json
import os
import sys
import re, ast, math
from collections import namedtuple
from bs4 import BeautifulSoup
from datetime import datetime
import nbconvert
import nbformat
import numpy as np

from typing import Dict, List, Tuple


PASS = "PASS"
FAIL_STDERR = "Program produced an error - please scroll up for more details."
FAIL_JSON = (
    "Expected program to print in json format. "
    "Make sure the only print statement is a print(json.dumps...)!"
)
EPSILON = 1e-4
NUMPY_EPSILON = 1e-3

TEXT_FORMAT = "text"
NUMPY_FORMAT = "np"
PNG_FORMAT = "png"
HTML_FORMAT = "html"
Question = namedtuple("Question", ["number", "weight", "format"])

questions = [
    # stage 1
    Question(number=1, weight=5, format=HTML_FORMAT),
    Question(number=2, weight=5, format=NUMPY_FORMAT),
    Question(number=3, weight=5, format=NUMPY_FORMAT),
    Question(number=4, weight=5, format=NUMPY_FORMAT),
    Question(number=5, weight=5, format=NUMPY_FORMAT),
    Question(number=6, weight=5, format=TEXT_FORMAT),
    Question(number=7, weight=5, format=NUMPY_FORMAT),
    Question(number=8, weight=10, format=PNG_FORMAT),
    Question(number=9, weight=5, format=HTML_FORMAT),
    Question(number=10, weight=5, format=NUMPY_FORMAT),
    Question(number=11, weight=5, format=TEXT_FORMAT),
    Question(number=12, weight=5, format=TEXT_FORMAT),
    Question(number=13, weight=5, format=PNG_FORMAT),
    Question(number=14, weight=25, format=PNG_FORMAT),
]
question_nums = [q.number for q in questions]

expected_json = {
    "1": 8,
    "2": [0.04930535, 0.07936743, 0.20509542, 0.03044255, 0.03537576],
    "3": [0.0550033, 0.12300135, 0.27048759, 0.05022482, 0.04293064],
    "4": [0.03887413, 0.07140925, 0.22326, 0.03887413, 0.07028827],
    "5": [0.04783065, 0.09832767, 0.3671606, 0.04975052, 0.04702566],
    "6": -423.2291853385189,
    "10": [0.1027832, 0.05908203, 0.00805664, 0.05419922, 0.04199219],
}


def parse_df_html_table(html: str, question: int = None) -> Dict[Tuple, List]:
    """
    Extract dataframe from html
    :param html: which contains output df, such as expected.html
    :param question: question number
    :return: Dict of rows
    """
    soup = BeautifulSoup(html, "html.parser")

    if not question:
        tables = soup.find_all("table")
        assert len(tables) == 1
        table = tables[0]
    else:
        # find a table that looks like this:
        # <table data-question="6"> ...
        table = soup.find("table", {"data-question": str(question)})

    rows = []
    for tr in table.find_all("tr"):
        rows.append([])
        for cell in tr.find_all(["td", "th"]):
            rows[-1].append(cell.get_text())

    cells = {}
    for r in range(1, len(rows)):
        for c in range(1, len(rows[0])):
            rname = rows[r][0]
            cname = rows[0][c]
            cells[(rname, cname)] = rows[r][c]
    return cells


def extract_question_num(cell: Dict) -> int:
    """
    find a comment something like this: #q10
    :param cell: Dict of parsed ipynb
    :return:
    """
    for line in cell.get("source", []):
        line = line.strip().replace(" ", "").lower()
        m = re.match(r"\#q(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def rerun_notebook(orig_notebook: str) -> Dict:
    """
    rerun notebook and return parsed JSON

    :param orig_notebook: path to jupyter notebook
    :return: JSON parsed ipynb
    """
    new_notebook = "cs-320-test.ipynb"

    # re-execute it from the beginning
    with open(orig_notebook, encoding="utf-8") as f:
        nb = nbformat.read(f, as_version=nbformat.NO_CONVERT)
    ep = nbconvert.preprocessors.ExecutePreprocessor(timeout=120, kernel_name="python3")
    try:
        ep.preprocess(nb, {"metadata": {"path": os.getcwd()}})
    except nbconvert.preprocessors.CellExecutionError:
        msg = f'Error executing the notebook "{orig_notebook}".\n\n'
        msg += f'See notebook "{new_notebook}" for the traceback.'
        print(msg)
        raise
    finally:
        with open(new_notebook, mode="w", encoding="utf-8") as f:
            nbformat.write(nb, f)

    # Note: Here we are saving and reloading, this isn't needed but can help student's debug
    # parse notebook
    with open(new_notebook, encoding="utf-8") as f:
        nb = json.load(f)
    return nb


def get_cell_output(cell: Dict, mime: str):
    """
    Extract output from cell
    :param cell: Dict representing ipynb cell
    :param mime: type of output (eg: text/html, text/plain, image/png, etc.)
    :return: parsed output
    """
    outputs = cell.get("outputs", [])
    actual_lines = None
    for out in outputs:
        lines = out.get("data", {}).get(mime, [])
        if lines:
            actual_lines = lines
            break
    return actual_lines


def check_cell_text(qnum: int, cell: Dict, is_numpy_array: bool = False) -> str:
    """
    Check text type output in jupyter cell

    :param qnum: Question number
    :param cell: Parsed ipynb Dict
    :param is_numpy_array: Handle numpy arrays
    :return: PASS or FAIL
    """
    if len(cell.get("outputs", [])) == 0:
        return "no outputs in an Out[N] cell"

    actual_lines = get_cell_output(cell, "text/plain")
    if actual_lines == None:
        return (
            "no Out[N] output found for cell (note: printing the output does not work)"
        )
    expected = expected_json[str(qnum)]
    expected_mismatch = False
    actual = "".join(actual_lines)
    try:
        if is_numpy_array:
            actual = actual.lstrip("array")
        actual = ast.literal_eval(actual)
    except Exception as e:
        print("COULD NOT PARSE THIS CELL:")
        print(actual)
        if not is_numpy_array and "array" in actual:
            print(f"ERROR: numpy array passed but expected format {type(expected)}")
        raise e

    if type(expected) != type(actual):
        return "expected an answer of type %s but found one of type %s" % (
            type(expected),
            type(actual),
        )
    elif type(expected) == float:
        if not math.isclose(actual, expected, rel_tol=1e-02, abs_tol=1e-02):
            expected_mismatch = True

    elif is_numpy_array:
        if np.linalg.norm(np.array(expected) - np.array(actual)) > NUMPY_EPSILON:
            expected_mismatch = True

    elif type(expected) in (list, tuple):
        try:
            extra = set(actual) - set(expected)
            missing = set(expected) - set(actual)
            if missing:
                return f"missing {len(missing)} entries list, such as: {missing}"
            elif extra:
                return (
                    f"found {len(extra)} unexpected entries, such as: {list(extra)[0]}"
                )
            elif len(actual) != len(expected):
                return f"expected {len(expected)} entries in the list but found {len(actual)}"
            else:
                for i, (a, e) in enumerate(zip(actual, expected)):
                    if a != e:
                        return f"found {a} at position {i} but expected {e}"
        except TypeError:
            if len(actual) != len(expected):
                return f"expected {len(expected)} entries in the list but found {len(actual)}"
            for i, (a, e) in enumerate(zip(actual, expected)):
                if a != e:
                    # this happens when the list contains dicts.  Just do a simple comparison
                    return f"found {a} at position {i} but expected {e}"
    elif type(expected) == tuple:
        if len(expected) != len(actual):
            expected_mismatch = True
        try:
            for idx in range(len(expected)):
                if not math.isclose(
                    actual[idx], expected[idx], rel_tol=1e-02, abs_tol=1e-02
                ):
                    expected_mismatch = True
        except:
            expected_mismatch = True

    else:
        if expected != actual:
            expected_mismatch = True

    if expected_mismatch:
        return f"found {actual} in cell {qnum} but expected {expected}"

    return PASS


def diff_df_cells(
    actual_cells: Dict[Tuple, List], expected_cells: Dict[Tuple, List]
) -> str:
    """
    Compares two extracted dataframes
    :return: PASS or FAIL
    """
    for location, expected in expected_cells.items():
        location_name = f"column {location[1]} at index {location[0]}"
        actual = actual_cells.get(location, None)
        if not actual:
            return f"value missing for {location_name}"
        try:
            actual_float = float(actual)
            expected_float = float(expected)
            if math.isnan(actual_float) and math.isnan(expected_float):
                return PASS
            if not math.isclose(
                actual_float, expected_float, rel_tol=1e-02, abs_tol=1e-02
            ):
                print(type(actual_float), actual_float)
                return f"found {actual} in {location_name} but it was not close to expected {expected}"

        except Exception as e:
            if actual != expected:
                return f"found '{actual}' in {location_name} but expected '{expected}'"
    return PASS


def check_cell_html(qnum: int, cell: Dict) -> str:
    """
    Match cell output with expected.html etc

    :param qnum: Question number
    :param cell: Parsed ipynb Dict
    :return: PASS or FAIL
    """
    actual_lines = get_cell_output(cell, "text/html")
    if actual_lines == None:
        return (
            "no Out[N] output found for cell (note: printing the output does not work)"
        )

    try:
        actual_cells = parse_df_html_table("".join(actual_lines))
    except Exception as e:
        print("ERROR!  Could not find table in notebook")
        raise e

    try:
        with open("expected.html") as f:
            expected_cells = parse_df_html_table(f.read(), qnum)
    except Exception as e:
        print("ERROR!  Could not find table in expected.html")
        raise e

    return diff_df_cells(actual_cells, expected_cells)


def check_cell_png(qnum: int, cell: Dict) -> str:
    """
    Check if output type is png
    WARN: doesnt check contents

    :param qnum: Question number
    :param cell: Parsed ipynb Dict
    :return: PASS or FAIL
    """
    for output in cell.get("outputs", []):
        if "image/png" in output.get("data", {}):
            return PASS
    return "no plot found"


def check_cell(question: Question, cell: Dict) -> str:
    """
    Checks a question
    :param question: Question type
    :param cell: Parsed ipynb Dict
    :return: PASS or FAIL
    """
    print("Checking question %d" % question.number)
    if question.format == TEXT_FORMAT:
        return check_cell_text(question.number, cell)
    elif question.format == NUMPY_FORMAT:
        return check_cell_text(question.number, cell, is_numpy_array=True)
    elif question.format == PNG_FORMAT:
        return check_cell_png(question.number, cell)
    elif question.format == HTML_FORMAT:
        return check_cell_html(question.number, cell)
    raise Exception("invalid question type")


def grade_answers(cells):
    results = {"score": 0, "tests": [], "date": datetime.now().strftime("%m/%d/%Y")}

    for question in questions:
        status = "not found"

        if question.number in cells:
            # does it match the expected output?
            status = check_cell(question, cells[question.number])

        row = {"test": question.number, "result": status, "weight": question.weight}
        results["tests"].append(row)

    return results


def main():
    # rerun everything
    orig_notebook = "main.ipynb"
    if len(sys.argv) > 2:
        print("Usage: test.py main.ipynb")
        return
    elif len(sys.argv) == 2:
        orig_notebook = sys.argv[1]

    # make sure directories are properly setup
    nb = rerun_notebook(orig_notebook)

    # breakpoint()

    # extract cells that have answers
    answer_cells = {}
    for cell in nb["cells"]:
        q = extract_question_num(cell)
        if not q:
            continue
        if not q in question_nums:
            print(
                f"Question {q} not found. \nPlease ensure the header is marked with #q{q}."
            )
            continue
        answer_cells[q] = cell

    # do grading on extracted answers and produce results.json
    results = grade_answers(answer_cells)
    passing = sum(t["weight"] for t in results["tests"] if t["result"] == PASS)
    total = sum(t["weight"] for t in results["tests"])

    functionality_score = 100.0 * passing / total
    results["score"] = functionality_score

    print("\nSummary:")
    for test in results["tests"]:
        print(f"\t Question {test['test']}: {test['result']}")

    print(f"\nTOTAL SCORE: {results['score']:.2f}")
    with open("result.json", "w") as f:
        f.write(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
