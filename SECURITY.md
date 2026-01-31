# Security Policy

## Overview

This security policy outlines the security practices, data handling requirements, and vulnerability reporting procedures for the Bank Statement Parser project. This software processes sensitive financial data including bank account information, transaction details, and personally identifiable information (PII) that requires strict compliance with financial regulations.

## Data Classification

### High Sensitivity Data
- **IBAN (International Bank Account Numbers)** - Extracted and processed by CAMT parser
- **Account IDs** - Retrieved from bank statements
- **Debtor/Creditor Names** - Personal/business names from transactions
- **Transaction References** - May contain personal identifiers
- **Initiating Party Names** - PAIN.001 payment initiator information

### Regulatory Compliance
This software must comply with:
- **GDPR (General Data Protection Regulation)** - Article 5(1)(f) data security requirements
- **PCI DSS** - Payment card industry standards (if processing card data)
- **PSD2** - European Payment Services Directive
- **Local Data Protection Laws** - Jurisdiction-specific requirements

## Security Requirements

### 1. Data Processing
- **Data Minimization**: Only process necessary financial data fields
- **Encryption**: All PII must be encrypted at rest and in transit
- **Access Control**: Implement role-based access to financial data
- **Audit Logging**: Log all data access and processing activities

### 2. PII Protection
- **No PII in Logs**: Never log account numbers, names, or other PII to console or files
- **Data Anonymization**: Consider masking/hashing PII for non-production use
- **Retention Limits**: Implement data retention policies per regulatory requirements
- **Right to Erasure**: Support GDPR data deletion requests

### 3. System Security
- **Input Validation**: Validate all XML input files for malicious content
- **XML Security**: Protect against XXE (XML External Entity) attacks
- **Dependency Security**: Regular security scanning of dependencies
- **Code Security**: Static analysis security testing (SAST)

## Current Security Vulnerabilities

### Critical Issues Identified
1. **PII Exposure in Console Output** (CRITICAL)
   - Location: `pain001_parser.py:88`
   - Issue: Initiating party names printed to console
   - Regulation: GDPR Art. 5(1)(f)
   - Remediation: Remove or mask PII in output

2. **PII Processing Without Encryption** (HIGH)
   - Location: `camt_parser.py:232-233`, `camt_parser.py:285`
   - Issue: IBAN, debtor/creditor names processed in plaintext
   - Regulation: GDPR Art. 32
   - Remediation: Implement field-level encryption

3. **Insecure Log Configuration** (MEDIUM)
   - Location: Multiple files with logger usage
   - Issue: No PII filtering in log handlers
   - Regulation: GDPR Art. 5(1)(f)
   - Remediation: Implement PII-aware logging filters

## Secure Development Practices

### Code Review Requirements
- All code changes must undergo security review
- Focus on PII handling and data flow validation
- Verify no sensitive data in error messages or logs
- Check for XML security vulnerabilities

### Testing Requirements
- Security unit tests for PII masking
- Integration tests with sanitized test data
- Penetration testing for XML parsing components
- GDPR compliance validation tests

### Dependency Management
- Regular dependency vulnerability scanning
- Automated security updates for critical vulnerabilities
- License compliance verification
- Supply chain security validation

## Data Handling Guidelines

### For Developers
1. **Never log PII**: Use placeholders like `[MASKED_ACCOUNT]` instead
2. **Sanitize test data**: Use fake/synthetic data for testing
3. **Validate inputs**: Check XML structure and content before processing
4. **Encrypt sensitive fields**: Use AES-256 for PII fields in storage
5. **Minimize data scope**: Only extract necessary fields from bank files

### For Users
1. **Secure file handling**: Ensure bank statement files are from trusted sources
2. **Output security**: Secure any generated CSV/Excel files containing financial data
3. **Data retention**: Delete processed files when no longer needed
4. **Access control**: Restrict access to systems processing financial data

## Incident Response

### Security Incident Classification
- **P0 - Critical**: Data breach involving PII exposure
- **P1 - High**: Potential unauthorized access to financial data
- **P2 - Medium**: Security vulnerability in production
- **P3 - Low**: Security best practice violation

### Response Procedures
1. **Immediate containment**: Stop processing and isolate affected systems
2. **Assessment**: Determine scope and impact of security incident
3. **Notification**: Report to relevant authorities within 72 hours (GDPR requirement)
4. **Remediation**: Implement fixes and security improvements
5. **Documentation**: Record incident details and lessons learned

## Compliance Monitoring

### Regular Audits
- Quarterly PII handling compliance review
- Annual third-party security assessment
- Continuous automated vulnerability scanning
- Regular penetration testing

### Compliance Reporting
- Monthly security metrics dashboard
- Quarterly compliance status reports
- Annual regulatory compliance certification
- Incident response effectiveness reviews

## Contact Information

For security-related questions or concerns:
- **Security Team**: security@bankstatementparser.com
- **Data Protection Officer**: dpo@bankstatementparser.com
- **Emergency Security Hotline**: [To be defined]

---

**Document Version**: 1.0
**Last Updated**: 2026-01-30
**Next Review**: 2026-07-30
**Owner**: Chief Compliance Officer