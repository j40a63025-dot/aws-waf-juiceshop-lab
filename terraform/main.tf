terraform {
  required_version = "~> 1.14.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.35"
    }
  }
}

variable "web_acl_arn" {
  description = "Existing regional AWS WAFv2 web ACL ARN; no ACL is provisioned."
  type        = string

  validation {
    condition     = can(regex("^arn:aws(-[a-z]+)*:wafv2:[a-z0-9-]+:[0-9]{12}:regional/webacl/[^/]+/[0-9a-f-]+$", var.web_acl_arn))
    error_message = "Provide an existing regional AWS WAFv2 web ACL ARN."
  }
}

provider "aws" {
  region              = split(":", var.web_acl_arn)[3]
  allowed_account_ids = [split(":", var.web_acl_arn)[4]]
}

resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-telemetry-${split("/", var.web_acl_arn)[1]}"
  retention_in_days = 14
}

resource "aws_wafv2_web_acl_logging_configuration" "waf" {
  resource_arn            = var.web_acl_arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  dynamic "redacted_fields" {
    for_each = toset(["authorization", "cookie"])
    content {
      single_header {
        name = redacted_fields.value
      }
    }
  }
}
