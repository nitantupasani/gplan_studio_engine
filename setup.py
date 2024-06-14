from setuptools import setup, find_packages

packages = [
    'contourpy==1.1.1',
    'cycler==0.11.0',
    'fonttools==4.42.1',
    'fpdf==1.7.2',
    'kiwisolver==1.4.5',
    'matplotlib==3.8.0',
    'networkx==3.1',
    'numpy==1.26.0',
    'packaging==23.1',
    'Pillow==10.0.1',
    'pyparsing==3.1.1',
    'python-dateutil==2.8.2',
    'scipy==1.11.3',
    'shapely==2.0.1',
    'six==1.16.0',
]

setup(
    name='GPLAN',
    version='1.0',
    packages=find_packages(),
    install_requires=packages,
    python_requires='>=3.9',
    url='https://gplan.in',
)
