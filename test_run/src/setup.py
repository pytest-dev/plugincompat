from distutils.core import setup

setup(
    name="myplugin",
    version="1.0.0",
    py_modules=["myplugin"],
    entry_points={"pytest11": ["myplugin=myplugin"]},
)
