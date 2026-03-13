"""A Python Pulumi program"""

import pulumi as p
import pulumi_cloudflare as cloudflare

from deploy_schlemmer_maul_com import model

component_config = model.ComponentConfig.model_validate(p.Config().get_object('config'))

config = p.Config()
stack = p.get_stack()
org = p.get_organization()

cloudflare_provider = cloudflare.Provider(
    'cloudflare',
)

zone = cloudflare.get_zone_output(
    name=component_config.cloudflare.zone,
    opts=p.InvokeOptions(provider=cloudflare_provider),
)


IP = '178.63.21.185'

for name, content in [
    ('*', IP),
    ('www', IP),
    ('@', IP),
]:
    cloudflare.Record(
        name,
        proxied=False,
        name=name,
        type='A',
        content=content,
        zone_id=zone.id,
        ttl=60,
        opts=p.ResourceOptions(provider=cloudflare_provider),
    )

cloudflare.Record(
    'MX',
    proxied=False,
    name='@',
    type='MX',
    content='schlemmermaul-com02c.mail.protection.outlook.com',
    priority=0,
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)

cloudflare.Record(
    'autodiscover',
    proxied=False,
    name='autodiscover',
    type='CNAME',
    content='autodiscover.outlook.com',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)

cloudflare.Record(
    'selector1._domainkey',
    proxied=False,
    name='selector1._domainkey',
    type='CNAME',
    content='selector1-schlemmermaul-com02c._domainkey.schlemmermaul.d-v1.dkim.mail.microsoft',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)

cloudflare.Record(
    'selector2._domainkey',
    proxied=False,
    name='selector2._domainkey',
    type='CNAME',
    content='selector2-schlemmermaul-com02c._domainkey.schlemmermaul.d-v1.dkim.mail.microsoft',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)


cloudflare.Record(
    'SPF',
    proxied=False,
    name='@',
    type='TXT',
    content=f'"v=spf1 include:spf.protection.outlook.com ip4:{IP} -all"',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)

cloudflare.Record(
    'DMARC',
    proxied=False,
    name='_dmarc',
    type='TXT',
    content='"v=DMARC1; p=reject; rua=mailto:dmarc@schlemmer-maul.com; ruf=mailto:dmarc@schlemmer-maul.com; fo=0; adkim=s; aspf=s; pct=100; rf=afrf; ri=86400; sp=reject"',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)

cloudflare.Record(
    'DKIM',
    proxied=False,
    name='dkim._domainkey',
    type='TXT',
    content='"v=DKIM1;k=rsa;t=s;s=email;p=MIICIjANBgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEAwuKiYimc+axuymMKXDfvWPimGafrdNMNEGgmbser6tUXCOkDjft94CbeU072AFA9UbGUKey/v+Qv/pT/bU5sYk5bFWUT7vzOpgPgCE6ulyqHV+Fcmfxd1TUAIhuQrI0Eg9GY7hD++iefPF+vrntnhV3/TCY2rwMkivqQv7WYLknhE5lQW83bOZQrhpNoYGidJECso6F7BU2qmTXM3IYmFViaQ/eelfMcK+qWIdSE+Xjhi2KdaYpBOuGZudkkVa42sbP/sMwkTcdKXHNrnDcNsN1KTvBAY6G7cj10USmc6ytbnCKXj0vwVbOkcrJXzEX4lPNtA3vFUt3hyRGSMJpJB8rRVqHKXTo+YwAloJ1MG+PwypMXn/JxC6BWSwUVcnyFJAEp2Qc+7fvSbxJ+6FchDJ0lbJhLRx30Y10XwbJRHqroEexhB1U8cWbR8+oUhXz2rbeYXN/XVzKTE4SySNWtdrgcZHFe2yPqictZCxIWovNPcn6OTJv/a35E48oJ98Cg4RYyEsASHbZnymxDX2LaV1n6NjR9HeTUOExkXeXbSPIvGqyTqLMNCBNHe8qpVFV9ISDmposCtVf2MeMJNc7NKQjAbalTSjZjMt+s//Yqx+VihH2VIWMMCCCep+9sjGue2xlrrhajuEy2uyP6mRv7+8RiTj9hvTiL6PKNPZ6PtkCAwEAAQ=="',
    zone_id=zone.id,
    ttl=60,
    opts=p.ResourceOptions(provider=cloudflare_provider),
)
