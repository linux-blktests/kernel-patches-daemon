#!/bin/bash
#
# Copyright (C) 2026 Western Digital Corporation or its affiliates.
# KPD often stops due to non-critical failures. Just restart KPD.

declare ret
declare count
declare subject
declare ADDR
declare MAX_RETRY=50
declare REQUESTS_CA_BUNDLE
declare conf
declare suffix
declare KPD_ERR_LOG

usage() {
	echo "$0 [OPTS] [CONFIG_JSON]"
	echo -e "OPTS:\t-m MAIL_ADDR\tSend failure log tail on failure"
	echo -e "\t-r COUNT\tRepeat count: default ${MAX_RETRY}"
	echo -e "\t-c PATH\t\tSpecify REQUESTRS_CA_BUNDLE path"
	echo -e "\t-h\t\tShow this help"
	exit
}

while (( $# >= 1 )); do
	case "$1" in
		-m) ADDR="$2";
		    shift 2;;
		-r) MAX_RETRY="$2";
		    shift 2;;
		-c) REQUESTS_CA_BUNDLE="$2";
		    if [[ ! -r $REQUESTS_CA_BUNDLE ]]; then
			    echo "Invalid REQUESTS_CA_BUNDLE"
			    exit 1
		    fi
		    shift 2;;
		-l) KPD_ERR_LOG="$2";
		    shift 2;;
		-h) usage;;
		*) break;;
	esac
done

conf=${1:-configs/kpd.json}
suffix=${conf##*/}
suffix=${suffix/.json/}
KPD_ERR_LOG=/tmp/kpd_${suffix}.err
export REQUESTS_CA_BUNDLE

run() {
	poetry run python -m kernel_patches_daemon --config "${conf}" \
	       --label-color configs/labels.json |& \
	       tee -a /var/kpd/kpd_"${suffix}".log
}

for ((count = 0; count < MAX_RETRY; count++)); do
	run
	ret=$?
	{
		echo "KPD stopped: ret=${ret}"
		date
	} | tee -a /tmp/kpd_"${suffix}"_sh.log

	subject="KPD stopped: ret=${ret}"
	if ((count < MAX_RETRY - 1)); then
		subject+=": restarting"
	else
		subject+=": script stop"
	fi
	grep ERROR /var/kpd/kpd_"${suffix}".log | tail -3 > "$KPD_ERR_LOG"
	if [[ -n $ADDR ]]; then
		mail --subject="${subject}" "$ADDR" < "$KPD_ERR_LOG"
	fi
done
