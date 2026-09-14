from setuptools import find_packages, setup

package_name = 'vln_core'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='sousuke',
    maintainer_email='sousuke@xjtlu.edu.cn',
    description='Core protocol validation, action adapter, and safety filter for XJTLU VLN',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vln_action_adapter_node = vln_core.nodes.action_adapter_node:main',
            'vln_safety_node = vln_core.nodes.safety_node:main',
        ],
    },
)
