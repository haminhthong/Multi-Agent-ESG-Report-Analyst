terraform { required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } } }
variable "aws_region" { default = "ap-southeast-1" }
variable "image" { type = string }
provider "aws" { region = var.aws_region }
resource "aws_ecs_cluster" "this" { name = "esg-report-analyst" }
resource "aws_cloudwatch_log_group" "this" { name = "/ecs/esg-report-analyst" retention_in_days = 14 }
output "cluster_name" { value = aws_ecs_cluster.this.name }

