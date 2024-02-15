import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

description = (
    "Application to play Pokemon Showdown using heuristic-based agents. Include a simple battle engine."
)

setuptools.setup(
    name="poke_engine",
    version="1.0.0",
    author="pmariglia", 
    description=description,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/SirSkaro/pokemon-expectiminimax",
    packages=setuptools.find_packages(exclude=["tests", "tests.*", "Dockerfile", ""]),
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
    python_requires='>=3.8',
    install_requires=[]
)