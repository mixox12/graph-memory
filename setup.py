from setuptools import setup, find_packages

setup(
    name="graph-memory",
    version="1.0.0",
    packages=find_packages(),
    package_data={
        "graph_memory": ["../web/*"],
    },
    include_package_data=True,
    install_requires=[
        "requests>=2.28.0",
    ],
    extras_require={
        "neo4j-driver": ["neo4j>=5.10.0"],
        "dev": ["pytest>=7.0.0", "pytest-cov>=4.0.0"],
    },
    entry_points={
        "console_scripts": [
            "graph-memory=graph_memory.cli:main",
            "graphrag=graph_memory.cli:main",
            "graph-memory-mcp=graph_memory.mcp_server:run_mcp_server",
        ],
    },
)
