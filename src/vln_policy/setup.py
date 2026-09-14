from setuptools import find_packages, setup

package_name = 'vln_policy'

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
    description='Vision-Language Navigation policy runner and mock policy for XJTLU VLN',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vln_mock_policy_node = vln_policy.nodes.mock_policy_node:main',
            'vln_door_nav_policy_node = vln_policy.nodes.door_nav_policy_node:main',
        ],
    },
)
