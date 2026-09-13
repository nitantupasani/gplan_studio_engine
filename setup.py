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
    'PyYAML==6.0.1',
    'scipy==1.11.3',
    'shapely==2.0.5',
    'six==1.16.0',
]

# Non-Python files that must land next to their modules in a built wheel.
# GPLAN/structural reads both sets by path off __file__ (data/_loader.py resolves
# data/<name>.yaml; the response schema sits at structural/schema/), so a wheel
# without them raises FileNotFoundError on the first clause call. schema/ has no
# __init__.py, so its glob is declared on the parent package.
package_data = {
    'GPLAN.structural': ['schema/*.json'],
    'GPLAN.structural.data': ['*.yaml'],
}

setup(
    name='GPLAN',
    version='1.0',
    packages=find_packages(),
    package_data=package_data,
    # explicit: the repo carries no MANIFEST.in and no SCM plugin, so
    # package_data above is the whole declaration and nothing is picked up
    # implicitly by setuptools version.
    include_package_data=False,
    install_requires=packages,
    python_requires='>=3.9',
    url='https://gplan.in',
)
