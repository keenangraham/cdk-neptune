from aws_cdk import App
from aws_cdk import CfnOutput
from aws_cdk import Duration
from aws_cdk import Environment
from aws_cdk import Stack

from aws_cdk.aws_neptune_alpha import DatabaseCluster

from constructs import Construct


app = App()

class NeptuneStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)


neptune_stack = NeptuneStack(
    app,
    'NeptuneStack',
    env=Environment(
        account='618537831167',
        region='us-west-2',
    )
)


app.synth()
