output "public_ip" {
  description = "Public IP of the ShopSense server"
  value       = aws_eip.shopsense_ip.public_ip
}

output "ssh_command" {
  description = "SSH command to connect to the server"
  value       = "ssh -i shopsense-key.pem ubuntu@${aws_eip.shopsense_ip.public_ip}"
}

output "app_url" {
  description = "ShopSense application URL"
  value       = "http://${aws_eip.shopsense_ip.public_ip}"
}
