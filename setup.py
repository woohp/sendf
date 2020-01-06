from setuptools import setup, find_packages

setup(
    name="sendf",
    packages=find_packages(),
    version="0.0.4",
    description="Easily send files.",
    author="Hui Peng Hu",
    author_email="woohp135@gmail.com",

    python_requires='>=3.6',
    py_modules=["sendf", "upnp"],
    scripts=["scripts/sendf"],
    install_requires=open("requirements.txt").read().split(),
)
