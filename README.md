# homcc - Home-Office friendly distcc replacement

---

## Documentation

---

###!TODO
[comment]: #TODO(s.pirsch)


## Development

---

### Setup
- Install required dependencies:<br/>
  `python -m pip install -r requirements.txt`


### Testing
- Tests and test coverage analysis are performed via [`pytest`](https://github.com/pytest-dev/pytest)
- Execute all tests in `./tests` and produce a test and coverage summary: `pytest -v -rfEs --cov=homcc`


### Linting
- Analyze all python files with [`pylint`](https://github.com/PyCQA/pylint): `pylint -v --rcfile=.pylintrc *.py **/*.py`
- Check static typing of all python files with [`mypy`](https://github.com/python/mypy): `mypy *.py **/*.py`


### Formatting
- Formatting and format check are executed via [`black`](https://github.com/psf/black)
- Check the formatting of all python files and list the required changes:<br/>
  `black --check --color --diff --verbose *.py **/*.py`
- Format a specified python file: `black ./path/to/file.py`