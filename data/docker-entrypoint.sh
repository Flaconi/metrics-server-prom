#!/usr/bin/env bash

# Be strict
set -e
set -u
set -o pipefail

# Function to store stdout and stderr in two different variables
# https://stackoverflow.com/questions/11027679/capture-stdout-and-stderr-into-different-variables
catch()
{
	eval "$({
	__2="$(
		{ __1="$("${@:3}")"; } 2>&1;
		ret=$?;
		printf '%q=%q\n' "$1" "$__1" >&2;
		exit $ret
		)"
	ret="$?";
	printf '%s=%q\n' "$2" "$__2" >&2;
	printf '( exit %q )' "$ret" >&2;
	} 2>&1 )";
}


###
### Start up
###
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
