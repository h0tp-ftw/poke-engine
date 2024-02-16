import setuptools

with open("README.md", "r", encoding='utf-8') as fh:
    long_description = fh.read()

description = (
    "Simplified Pokemon battle engine for game state searching. Forked from pmariglia's showdown project."
)

setuptools.setup(
    name="poke_engine",
    version="1.0.0",
    author="pmariglia", 
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/SirSkaro/poke-engine",
    packages=setuptools.find_packages(exclude=["tests", "tests.*", ""]),
    data_files=[('poke_engine', ['data/*.json', 'data/mods/*.json'])],
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU GENERAL PUBLIC",
        "Operating System :: OS Independent",
    ),
    python_requires='>=3.8',
    install_requires=[]
)