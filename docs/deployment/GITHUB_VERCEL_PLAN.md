# GitHub + Vercel Deployment Plan

## Target topology

GitHub → CI/CD → deployment platform → Namkeen ERP API/Web → PostgreSQL

GitHub is the intended source-control system. The consolidated repository is designed to become the single canonical repository.

Vercel can integrate with Git-based repositories and provide preview/production deployment workflows. Its current documentation also describes containerized HTTP-server deployment, but the exact production topology for this FastAPI + PostgreSQL ERP must be validated before committing the ERP API to Vercel.

## Recommended sequence

1. Create a private GitHub repository for Candidate 1.0.
2. Push this exact consolidated tree.
3. Verify GitHub Actions from a clean checkout.
4. Connect Vercel only after repository/CI validation.
5. Deploy a staging/preview environment.
6. Connect a dedicated staging PostgreSQL database.
7. Run migration smoke + UAT.
8. Only after successful staging validation configure production deployment.
9. Add the custom domain after the deployment topology is confirmed.

## Do not put in GitHub

- production `.env` files
- passwords
- JWT/auth secrets
- PostgreSQL private credentials
- Tally/GST/e-way credentials
- private object-storage credentials

Example configuration files are safe templates only.
