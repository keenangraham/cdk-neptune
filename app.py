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
from aws_cdk.aws_ecs import Secret as ECSSecret
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

from aws_cdk.aws_events import Rule
from aws_cdk.aws_events import Schedule
from aws_cdk.aws_events import EventPattern

from aws_cdk.aws_events_targets import EcsTask
from aws_cdk.aws_events_targets import ContainerOverride

from constructs import Construct

from shared_infrastructure.igvf_dev.environment import US_WEST_2
from shared_infrastructure.igvf_dev.network import DemoNetwork
from shared_infrastructure.igvf_dev.domain import DemoDomain


app = App()


class NeptuneStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        network = DemoNetwork(
            self,
            'DemoNetork',
        )

        domain = DemoDomain(
            self,
            'DemoDomain',
        )

        cluster = DatabaseCluster(
            self,
            'Neptune',
            vpc=network.vpc,
            instance_type=InstanceType.T3_MEDIUM,
            vpc_subnets=SubnetSelection(
                subnet_type=SubnetType.PUBLIC,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        cluster.connections.allow_default_port_from_any_ipv4('Open to the world')

        write_address = cluster.cluster_endpoint.socket_address
        read_address = cluster.cluster_read_endpoint.socket_address

        '''
        bastion_host = BastionHostLinux(
            self,
            'NeptuneBastionHost',
            instance_type=Ec2InstanceType('t3.nano'),
            vpc=network.vpc,
            subnet_selection=SubnetSelection(
                subnet_type=SubnetType.PUBLIC
            ),
        )
        '''
        
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
                    'SERVER_URL': 'https://graphviz.demo.igvf.org/server'
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
            vpc=network.vpc,
            desired_count=1,
            task_definition=task_definition,
            load_balancers=[
                ApplicationLoadBalancerProps(
                    name="lb",
                    public_load_balancer=True,
                    domain_name='graphviz.demo.igvf.org',
                    domain_zone=domain.zone,
                    listeners=[
                        ApplicationListenerProps(
                            name='listener',
                            certificate=domain.certificate
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
            vpc=network.vpc,
        )

        server_target_group.configure_health_check(
            path='/server/hello',
        )
        
        auth0_secret = Secret.from_secret_complete_arn(
           self,
           'Auth0Secret',
            secret_complete_arn='arn:aws:secretsmanager:us-west-2:109189702753:secret:graphviz/auth0secret-5s5lsK',
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

        load_data_docker_image = ContainerImage.from_asset(
            './',
            file='./docker/python/Dockerfile'
        )

        load_data_task_definition = FargateTaskDefinition(
            self,
            'LoadDataTask',
            cpu=1024,
            memory_limit_mib=3072,
            task_role=fargate.task_definition.task_role,
        )

        igvfd_secret = Secret.from_secret_complete_arn(
           self,
           'IGVFDSecret',
            secret_complete_arn='arn:aws:secretsmanager:us-west-2:109189702753:secret:indexing-service-portal-key-BdNl8x',
        )

        load_data_task_definition.add_container(
            'load-data',
            container_name='load-data',
            image=load_data_docker_image,
            environment={
                'NEPTUNE_ENDPOINT': write_address,
            },
            secrets={
                'IGVF_API_KEY': ECSSecret.from_secrets_manager(
                    igvfd_secret,
                    'BACKEND_KEY',
                ),
                'IGVF_API_SECRET': ECSSecret.from_secrets_manager(
                    igvfd_secret,
                    'BACKEND_SECRET_KEY',
                ),
            },
            logging=LogDriver.aws_logs(
                stream_prefix='load-data',
                mode=AwsLogDriverMode.NON_BLOCKING,
            ),
        )

        event_target = EcsTask(
            task_definition=load_data_task_definition,
            cluster=fargate.cluster,
            task_count=1,
            subnet_selection=SubnetSelection(
                subnet_type=SubnetType.PUBLIC
            ),
        )

        Rule(
            self,
            'LoadGraphData',
            schedule=Schedule.cron(
                minute='30',
                hour='10',
            ),
            targets=[
                event_target
            ],
        )

        Rule(
            self,
            'LoadGraphDataEvent',
            event_pattern=EventPattern(
                detail_type=[
                    'LoadGraphDataQUICK'
                ],
                source=[
                    'graphviz',
                ],
            ),
            targets=[
                event_target
            ]
        )

        full_reload_event_target = EcsTask(
            task_definition=load_data_task_definition,
            cluster=fargate.cluster,
            task_count=1,
            subnet_selection=SubnetSelection(
                subnet_type=SubnetType.PUBLIC
            ),
            container_overrides=[
                ContainerOverride(
                    container_name='load-data',
                    command=['python', 'load_data.py', 'full'],
                )
            ]
        )

        Rule(
            self,
            'LoadGraphDataEvent',
            event_pattern=EventPattern(
                detail_type=[
                    'LoadGraphDataFULL'
                ],
                source=[
                    'graphviz',
                ],
            ),
            targets=[
                full_reload_event_target
            ]
        )


neptune_stack = NeptuneStack(
    app,
    'NeptuneStack',
    env=US_WEST_2,
)


app.synth()
