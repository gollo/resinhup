#!/bin/bash

set -e

readonly _registry_default="registry.resinstaging.io/resin/resinhup resin/resinhup-test"

GREEN='\033[0;32m'
NC='\033[0m'
TAG=latest
REGISTRY=$_registry_default

# Help function
function help {
    cat << EOF
Run docker build and push for the supported images.
$0 <OPTION>

Options:
  -h, --help
        Display this help and exit.

  -d, --dockerfile
        Build and push only this Dockerfile. Otherwise all found will be used.

  -r, --registry
        List of one or more Docker registries to push to, without the trailing slash.
        Remember to change the corresponding value in conf/resinhup.conf as well.
        Default: "$_registry_default".

  -t, --tag
        By default push will be done to latest tag. This can be tweaked with this flag.

EOF
}

#
# MAIN
#

# Parse arguments
while [[ $# > 0 ]]; do
    arg="$1"

    case $arg in
        -h|--help)
            help
            exit 0
            ;;
        -d|--dockerfile)
            if [ -z "$2" ]; then
                echo "[ERROR] \"$1\" argument needs a value."
                exit 1
            fi
            DOCKERFILES=$2
            shift
            ;;
        -r|--registry)
            if [ -z "$2" ]; then
                echo "[ERROR] \"$1\" argument needs a value."
                exit 1
            fi
            REGISTRY=$2
            shift
            ;;
        -t|--tag)
            if [ -z "$2" ]; then
                echo "[ERROR] \"$1\" argument needs a value."
                exit 1
            fi
            TAG=$2
            shift
            ;;
        *)
            echo "[ERROR] Unrecognized option $1."
            exit 1
            ;;
    esac
    shift
done

# Get the absolute script location
pushd `dirname $0` > /dev/null 2>&1
SCRIPTPATH=`pwd`
popd > /dev/null 2>&1

if [ -z "$DOCKERFILES" ]; then
    DOCKERFILES=$(ls $SCRIPTPATH/../Dockerfile.*)
fi

for dockerfile in $DOCKERFILES; do
    dockerfile=$(basename $dockerfile)
    device=$(echo $dockerfile | cut --delimiter '.' -f2)
    if [ -z "$device" ]; then
        echo "ERROR: Can't detect device name for $dockerfile"
        exit 1
    fi
    printf "${GREEN}Running build for $device using $dockerfile ...${NC}\n"
    for registry in $REGISTRY; do
        printf "${GREEN}Tag and push for $device ...${NC}\n"
        docker build -t $registry:$TAG-$device -f ../$dockerfile $SCRIPTPATH/..
        docker push $registry:$TAG-$device
    done
done
