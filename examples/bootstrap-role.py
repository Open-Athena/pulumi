"""Example: Bootstrap role for a repo to manage its own AWS resources via Pulumi.

This would live in `ops` (or a central infra repo) and creates the IAM role that
other repos assume to run their own Pulumi stacks.
"""

import pulumi
import pulumi_aws as aws

# Config
config = pulumi.Config()
github_org = config.require("github_org")
github_repo = config.require("github_repo")

current = aws.get_caller_identity()

# The repo-specific role that GitHub Actions will assume
pulumi_role = aws.iam.Role(f"pulumi-{github_repo}",
    description=f"Pulumi role for {github_org}/{github_repo}",
    assume_role_policy=pulumi.Output.format("""{
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {
                "Federated": "arn:aws:iam::{0}:oidc-provider/token.actions.githubusercontent.com"
            },
            "Action": "sts:AssumeRoleWithWebIdentity",
            "Condition": {
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": "repo:{1}/{2}:*"
                }
            }
        }]
    }""", current.account_id, github_org, github_repo)
)

# Policy for what this repo can manage
# Customize per-repo based on what resources they need
pulumi_policy = aws.iam.Policy(f"pulumi-{github_repo}-policy",
    description=f"Pulumi permissions for {github_org}/{github_repo}",
    policy="""{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ManageOwnS3",
                "Effect": "Allow",
                "Action": ["s3:*"],
                "Resource": [
                    "arn:aws:s3:::REPO-SPECIFIC-BUCKET",
                    "arn:aws:s3:::REPO-SPECIFIC-BUCKET/*"
                ]
            },
            {
                "Sid": "ManageOwnIAM",
                "Effect": "Allow",
                "Action": [
                    "iam:CreatePolicy",
                    "iam:DeletePolicy",
                    "iam:GetPolicy",
                    "iam:GetPolicyVersion",
                    "iam:ListPolicyVersions",
                    "iam:CreatePolicyVersion",
                    "iam:DeletePolicyVersion"
                ],
                "Resource": "arn:aws:iam::*:policy/electrai-*"
            },
            {
                "Sid": "ReadOnly",
                "Effect": "Allow",
                "Action": ["sts:GetCallerIdentity"],
                "Resource": "*"
            }
        ]
    }"""
)

aws.iam.RolePolicyAttachment(f"pulumi-{github_repo}-attachment",
    role=pulumi_role.name,
    policy_arn=pulumi_policy.arn
)

# Export the role ARN - this gets set as PULUMI_AWS_ROLE var on the repo
pulumi.export("pulumi_role_arn", pulumi_role.arn)
