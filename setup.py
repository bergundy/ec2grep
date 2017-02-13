try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='shh',
    description='Shell helper in python',
    author='Roey Berman',
    author_email='roey.berman@gmail.com',
    packages=['shh'],
    verion='0.1',
    keywords=['shell', 'sh'],
    install_requires=[
    ],
    entry_points={
    }
)
