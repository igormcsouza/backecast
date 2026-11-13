"""Public frontend hosting: private S3 bucket behind CloudFront (OAC), on its own domain.

Same shape as Igor's other apps. A domain of its own (not `igormcsouza.github.io/backecast`) keeps the admin
login token in an origin no other site shares. The static export is uploaded by CI (deploy.yml), not by CDK.
"""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cf
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_route53 as r53
from aws_cdk import aws_route53_targets as r53t
from aws_cdk import aws_s3 as s3
from constructs import Construct

# Next's export has no trailingSlash: /admin is admin.html, / is index.html.
REWRITE = """function handler(e){var r=e.request;
if(r.uri.endsWith('/'))r.uri+='index.html';
else if(!r.uri.split('/').pop().includes('.'))r.uri+='.html';return r;}"""


def _zone(scope: Construct, zone_id: str, zone_name: str) -> r53.IHostedZone:
    return r53.HostedZone.from_hosted_zone_attributes(
        scope, "Zone", hosted_zone_id=zone_id, zone_name=zone_name
    )


class WebCertStack(Stack):
    """CloudFront only accepts ACM certificates from us-east-1."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain: str,
        zone_id: str,
        zone_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.cert = acm.Certificate(
            self,
            "Cert",
            domain_name=domain,
            validation=acm.CertificateValidation.from_dns(
                _zone(self, zone_id, zone_name)
            ),
        )


class WebStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        domain: str,
        zone_id: str,
        zone_name: str,
        cert: acm.ICertificate,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )
        headers = cf.ResponseHeadersPolicy(
            self,
            "Headers",
            security_headers_behavior=cf.ResponseSecurityHeadersBehavior(
                strict_transport_security=cf.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=Duration.days(365),
                    include_subdomains=True,
                    override=True,
                ),
                content_type_options=cf.ResponseHeadersContentTypeOptions(
                    override=True
                ),
                frame_options=cf.ResponseHeadersFrameOptions(
                    frame_option=cf.HeadersFrameOption.DENY, override=True
                ),
                referrer_policy=cf.ResponseHeadersReferrerPolicy(
                    referrer_policy=cf.HeadersReferrerPolicy.NO_REFERRER, override=True
                ),
            ),
        )
        self.dist = cf.Distribution(
            self,
            "Cdn",
            default_root_object="index.html",
            domain_names=[domain],
            certificate=cert,
            minimum_protocol_version=cf.SecurityPolicyProtocol.TLS_V1_2_2021,
            default_behavior=cf.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(self.bucket),
                viewer_protocol_policy=cf.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=headers,
                function_associations=[
                    cf.FunctionAssociation(
                        function=cf.Function(
                            self,
                            "Rewrite",
                            code=cf.FunctionCode.from_inline(REWRITE),
                            runtime=cf.FunctionRuntime.JS_2_0,
                        ),
                        event_type=cf.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            # A missing object is a 404 page, not S3's 403.
            error_responses=[
                cf.ErrorResponse(
                    http_status=403,
                    response_http_status=404,
                    response_page_path="/404.html",
                )
            ],
        )

        target = r53.RecordTarget.from_alias(r53t.CloudFrontTarget(self.dist))
        zone = _zone(self, zone_id, zone_name)
        r53.ARecord(self, "Alias", zone=zone, record_name=domain, target=target)
        r53.AaaaRecord(self, "Alias6", zone=zone, record_name=domain, target=target)

        CfnOutput(self, "BucketName", value=self.bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=self.dist.distribution_id)
        CfnOutput(self, "SiteUrl", value=f"https://{domain}")
