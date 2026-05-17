provider "aws" {
  region = var.aws_region
}

resource "aws_instance" "shopsense" {
  ami                    = "ami-0c7217cdde317cfec" # Ubuntu 22.04 us-east-1
  instance_type          = var.instance_type
  key_name               = "shopsense-key"
  vpc_security_group_ids = [aws_security_group.shopsense_sg.id]

  user_data = <<-EOF
    #!/bin/bash
    apt-get update -y
    apt-get install -y docker.io docker-compose-plugin git
    git clone https://github.com/yourusername/shopsense.git /home/ubuntu/shopsense
    cd /home/ubuntu/shopsense
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
  EOF

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  tags = {
    Name    = "shopsense-server"
    Project = "ShopSense"
  }
}

resource "aws_eip" "shopsense_ip" {
  instance = aws_instance.shopsense.id
  domain   = "vpc"

  tags = {
    Name = "shopsense-eip"
  }
}
