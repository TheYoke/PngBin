import setuptools

with open("README.md", "r", encoding='utf-8') as f:
    long_description = f.read()

setuptools.setup(
    name="PngBin",
    version="0.1.0",
    author="Nathan Young",
    author_email="theyoke3@gmail.com",
    description="Convert any binary data to a PNG image file and vice versa.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/TheYoke/PngBin",
    packages=['pngbin'],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
    license="MIT",
    install_requires=[
        "cryptography",
    ],
)
