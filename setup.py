from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="scrapemaster",
    version="0.2.0",
    author="ParisNeo",
    author_email="parisneoai@gmail.com",
    description="A versatile web scraping library with multiple techniques",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ParisNeo/ScrapeMaster",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
    ],
    python_requires=">=3.7",
    install_requires=[
        "requests>=2.25.1",
        "beautifulsoup4>=4.9.3",
        "lxml>=4.6.3",
        "selenium>=3.141.0",
    ],
    extras_require={
        "dev": ["pytest>=6.2.4", "flake8>=3.9.2", "black>=21.5b1"],
    },
)