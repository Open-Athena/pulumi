"""Test stack for the pulumi-v1 reusable workflow.

Creates lightweight, free AWS resources to exercise `pulumi preview --patch`
diff output, job summaries, and PR comments.
"""
import pulumi
import pulumi_aws as aws
import pulumi_tls as tls

config = pulumi.Config()
env = pulumi.get_stack()

# EC2 Key Pair (via TLS-generated key)
key = tls.PrivateKey("test-key", algorithm="ED25519")
key_pair = aws.ec2.KeyPair("test-key-pair",
    key_name=f"pulumi-v1-test-{env}",
    public_key=key.public_key_openssh,
)

# IAM Role (no trust policy; just exists for diff testing)
role = aws.iam.Role("test-role",
    name=f"pulumi-v1-test-{env}",
    assume_role_policy="""{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Deny",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }""",
)

# CloudWatch Log Group
log_group = aws.cloudwatch.LogGroup("test-log-group",
    name=f"/pulumi-v1/test/{env}",
    retention_in_days=1,
)

pulumi.export("key_pair_name", key_pair.key_name)
pulumi.export("role_arn", role.arn)
pulumi.export("log_group_name", log_group.name)
