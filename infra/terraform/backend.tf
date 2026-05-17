terraform {
  backend "s3" {
    bucket = "shopsense-terraform-state"
    key    = "shopsense/terraform.tfstate"
    region = "us-east-1"
  }
}
