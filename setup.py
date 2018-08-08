from setuptools import setup, find_packages
import os

if os.environ.get('CI_COMMIT_TAG'):
    version = os.environ['CI_COMMIT_TAG']
else:
    version = os.environ['CI_JOB_ID']

with open("README.md", "r") as f:
    long_description = f.read()

setup(
    name="pyrail",
    version=version,
    author="Jorim Tielemans",
    author_email="tielemans.jorim@gmail.com",
    description="Python wrapper for the iRail API",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://gitlab.com/tjorim/pyrail",
    install_requires=['requests>=2.0'],
    python_requires='>=3',
    packages=find_packages(),
    classifiers=(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
)
