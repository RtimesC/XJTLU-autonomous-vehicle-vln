from setuptools import find_packages, setup

package_name = 'vln_sim'

setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/sim_params.yaml']),
        ('share/' + package_name + '/launch', ['launch/vln_habitat_sim.launch.py']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='sousuke',
    maintainer_email='sousuke@xjtlu.edu.cn',
    description='Habitat simulation bridge and virtual vehicle environment for XJTLU VLN',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vln_habitat_bridge_node = vln_sim.nodes.habitat_bridge_node:main',
        ],
    },
)
