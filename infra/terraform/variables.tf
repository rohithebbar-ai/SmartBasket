variable "aws_region" {
  description = "AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t2.micro"
}

variable "your_ip" {
  description = "Your IP for SSH access — get from whatismyip.com. Never open SSH to 0.0.0.0/0."
  type        = string
  # No default — must be supplied explicitly on every plan/apply.
}
