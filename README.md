# Sunbeam Release Tools

## Overview

Repository for useful helpers for managing the promotion of charms and snaps
between channels and tracks on the Charmhub/Snapstore.

## Dependencies

The sunbeam-release tool makes use of charmcraft which can be installed as a
snap:

    sudo snap install --classic charmcraft
    sudo snap install snapcraft
    sudo snap install juju --channel=3.6/stable

charmcraft must also be logged into the charmhub in order for sunbeam-release
operators to work:

    charmcraft login

The revision of dependent project charms (which sunbeam-release does not
administer) is looked up with `juju info`, and dependent snaps with
`snap info`.

## Exported credentials (CI)

Promotion only releases existing revisions, it never uploads, so exported
credentials only need release permissions.

Charmhub credentials (consumed via the CHARMHUB_AUTH environment variable,
see charmcraft_env() in sunbeam_release/promote.py):

    charmcraft login --export charmhub-creds \
        --permission package-view --permission package-manage \
        --ttl 2592000
    export CHARMHUB_AUTH=$(cat charmhub-creds)

Snap Store credentials (SNAPCRAFT_STORE_CREDENTIALS is inherited by the
snapcraft promote calls):

    snapcraft export-login snapcraft-creds \
        --snaps openstack,openstack-hypervisor,cinder-volume,openstack-network-agents,manila-data,epa-orchestrator,consul-client \
        --acls package_access,package_release \
        --expires "$(date -u -d '+30 days' +%Y-%m-%dT%H:%M:%SZ)"
    export SNAPCRAFT_STORE_CREDENTIALS=$(cat snapcraft-creds)

Valid Snap Store ACLs are documented at
https://dashboard.snapcraft.io/docs/reference/v1/macaroon.html. The
--expires value must be UTC ISO 8601. The charmcraft TTL is in seconds
(2592000 = 30 days).

## Promotion of charms between channels

sunbeam-release can be used to compare and promote charms between channels
within a specific track on the charmhub:

    sunbeam-release promote --source edge --release antelope --dry-run

This command will compare the edge channel of all charms across the Sunbeam
charm set against the charm in the beta channel - any differences will be
detected and the relevant charmcraft commands will be printed to promote
the edge channel to beta channel.  The tracks to use for each charm are
determined by the release argument.

Dropping the '--dry-run' argument will also execute the charmcraft commands.
