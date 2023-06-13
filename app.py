from aws_cdk import App
from aws_cdk import CfnOutput
from aws_cdk import Duration
from aws_cdk import Environment
from aws_cdk import Stack
from aws_cdk import RemovalPolicy

from aws_cdk.aws_neptune_alpha import DatabaseCluster
from aws_cdk.aws_neptune_alpha import InstanceType

from aws_cdk.aws_ec2 import SubnetSelection
from aws_cdk.aws_ec2 import SubnetType

from constructs import Construct

from shared_infrastructure.cherry_lab.environments import US_WEST_2

from shared_infrastructure.cherry_lab.vpcs import VPCs


app = App()


class NeptuneStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpcs = VPCs(
            self,
            'VPCS',
        )

        cluster = DatabaseCluster(
            self,
            'Neptune',
            vpc=vpcs.default_vpc,
            instance_type=InstanceType.T3_MEDIUM,
            vpc_subnets=SubnetSelection(
                subnet_type=SubnetType.PUBLIC,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        cluster.connections.allow_default_port_from_any_ipv4("Open to the world")


neptune_stack = NeptuneStack(
    app,
    'NeptuneStack',
    env=US_WEST_2,
)


app.synth()
