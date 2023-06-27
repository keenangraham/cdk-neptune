from aws_cdk import App
from aws_cdk import CfnOutput
from aws_cdk import Duration
from aws_cdk import Environment
from aws_cdk import Stack
from aws_cdk import RemovalPolicy

from aws_cdk.aws_neptune_alpha import DatabaseCluster
from aws_cdk.aws_neptune_alpha import InstanceType

from aws_cdk.aws_ec2 import BastionHostLinux
from aws_cdk.aws_ec2 import InstanceType as Ec2InstanceType
from aws_cdk.aws_ec2 import SubnetSelection
from aws_cdk.aws_ec2 import SubnetType

from aws_cdk.aws_ecs import AwsLogDriverMode
from aws_cdk.aws_ecs import ContainerImage
from aws_cdk.aws_ecs import DeploymentCircuitBreaker
from aws_cdk.aws_ecs import LogDriver
from aws_cdk.aws_ecs import PortMapping
from aws_cdk.aws_ecs import Secret
from aws_cdk.aws_ecs import FargateTaskDefinition

from aws_cdk.aws_ecs_patterns import ApplicationLoadBalancedFargateService
from aws_cdk.aws_ecs_patterns import ApplicationLoadBalancedTaskImageOptions
from aws_cdk.aws_ecs_patterns import ApplicationMultipleTargetGroupsFargateService
from aws_cdk.aws_ecs_patterns import ApplicationTargetProps
from aws_cdk.aws_ecs_patterns import ApplicationListenerProps
from aws_cdk.aws_ecs_patterns import ApplicationLoadBalancerProps
from aws_cdk.aws_ecs_patterns import ApplicationLoadBalancedTaskImageProps

from aws_cdk.aws_elasticloadbalancingv2 import ApplicationTargetGroup
from aws_cdk.aws_elasticloadbalancingv2 import ListenerAction
from aws_cdk.aws_elasticloadbalancingv2 import ListenerCondition

from aws_cdk.aws_certificatemanager import Certificate

from aws_cdk.aws_route53 import HostedZone

from aws_cdk.aws_secretsmanager import Secret

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

        write_address = cluster.cluster_endpoint.socket_address
        read_address = cluster.cluster_read_endpoint.socket_address

        bastion_host = BastionHostLinux(
            self,
            'NeptuneBastionHost',
            instance_type=Ec2InstanceType('t3.nano'),
            vpc=vpcs.default_vpc,
            subnet_selection=SubnetSelection(
                subnet_type=SubnetType.PUBLIC
            ),
        )

        certificate = Certificate.from_certificate_arn(
            self,
            'DomainCertificate',
            'arn:aws:acm:us-west-2:618537831167:certificate/f2819fbb-0067-427e-b6a1-8a7b00362436',
        )

        hosted_zone = HostedZone.from_lookup(
            self,
            'HostedZone',
            domain_name='api.encodedcc.org',
        )
        
        docker_image = ContainerImage.from_asset(
            './browsers/gremlin-visualizer',
        )

        task_definition = FargateTaskDefinition(
            self,
            'GraphVizDef',
            cpu=1024,
            memory_limit_mib=3072,
        )

        task_definition.add_container(
            'client',
            container_name='client',
            command=['npm', 'run', 'client'],
            image=docker_image,
            environment={
                    'NEPTUNE_ENDPOINT': write_address,
                    'NODE_ENV': 'production',
                    'DANGEROUSLY_DISABLE_HOST_CHECK': 'true',
                    'SERVER_URL': 'https://graphviz.api.encodedcc.org/server'
            },
            logging=LogDriver.aws_logs(
                stream_prefix='client',
                mode=AwsLogDriverMode.NON_BLOCKING,
            ),
        )

        task_definition.add_container(
            'server',
            container_name='server',
            command=['npm', 'run', 'server'],
            image=docker_image,
            port_mappings=[
                PortMapping(
                    container_port=3001
                )
            ],
            environment={
                'NEPTUNE_ENDPOINT': write_address,
                'NODE_ENV': 'production',
            },
            secrets={
            },
            logging=LogDriver.aws_logs(
                stream_prefix='server',
                mode=AwsLogDriverMode.NON_BLOCKING,
            ),
        )

        fargate = ApplicationMultipleTargetGroupsFargateService(
            self,
            'graphviz',
            service_name='graphviz',
            vpc=vpcs.default_vpc,
            desired_count=1,
            task_definition=task_definition,
            load_balancers=[
                ApplicationLoadBalancerProps(
                    name="lb",
                    public_load_balancer=True,
                    domain_name='graphviz.api.encodedcc.org',
                    domain_zone=hosted_zone,
                    listeners=[
                        ApplicationListenerProps(
                            name="listener",
                            certificate=certificate,
                        )
                    ]
                )
            ],
            assign_public_ip=True,
            target_groups=[
                ApplicationTargetProps(
                    container_port=3000
                ),
            ],
        )

        server_target = fargate.service.load_balancer_target(
            container_name='server',
            container_port=3001,
        )

        server_target_group = ApplicationTargetGroup(
            self,
            'ServerTargetGroup',
            targets=[server_target],
            port=80,
            vpc=vpcs.default_vpc,
        )

        server_target_group.configure_health_check(
            path='/server/hello',
        )
        
        auth0_secret = Secret.from_secret_complete_arn(
           self,
           'Auth0Secret',
            secret_complete_arn='arn:aws:secretsmanager:us-west-2:618537831167:secret:test/auth0secret/graphviz-5CroJK',
        )

        fargate.listeners[0].add_action(
            'AuthAction',
            action=ListenerAction.authenticate_oidc(
                authorization_endpoint=auth0_secret.secret_value_from_json('AUTH_URL').unsafe_unwrap(),
                client_id=auth0_secret.secret_value_from_json('CLIENT_ID').unsafe_unwrap(),
                client_secret=auth0_secret.secret_value_from_json('CLIENT_SECRET'),
                issuer=auth0_secret.secret_value_from_json('ISSUER').unsafe_unwrap(),
                token_endpoint=auth0_secret.secret_value_from_json('TOKEN_URL').unsafe_unwrap(),
                user_info_endpoint=auth0_secret.secret_value_from_json('USER_INFO_URL').unsafe_unwrap(),
                next=ListenerAction.forward([fargate.target_groups[0]])
            )
        )

        fargate.listeners[0].add_action(
            'AuthAction',
            action=ListenerAction.authenticate_oidc(
                authorization_endpoint=auth0_secret.secret_value_from_json('AUTH_URL').unsafe_unwrap(),
                client_id=auth0_secret.secret_value_from_json('CLIENT_ID').unsafe_unwrap(),
                client_secret=auth0_secret.secret_value_from_json('CLIENT_SECRET'),
                issuer=auth0_secret.secret_value_from_json('ISSUER').unsafe_unwrap(),
                token_endpoint=auth0_secret.secret_value_from_json('TOKEN_URL').unsafe_unwrap(),
                user_info_endpoint=auth0_secret.secret_value_from_json('USER_INFO_URL').unsafe_unwrap(),
                next=ListenerAction.forward([server_target_group])
            ),
            conditions=[
                ListenerCondition.path_patterns(
                    [
                        '/server/*'
                    ]
                )
            ],
            priority=10,
        )


        CfnOutput(
            self,
            'NeptuneWriteEndpoint',
            value=write_address,
        )


neptune_stack = NeptuneStack(
    app,
    'NeptuneStack',
    env=US_WEST_2,
)


app.synth()
