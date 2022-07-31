#!/usr/bin/env python
#
# Copyright 2021 Garron Kramer (garron.kramer@gmail.com)
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.
#
#

from gitlab.const import GUEST_ACCESS
from okta.client import Client as OktaClient
from re import search
from time import sleep

import asyncio
import gitlab
import os
import re

# Global Variables
GITLAB_URL=os.getenv('GITLAB_URL') or 'https://gitlab.example.com'
GITLAB_TOKEN=os.getenv('GITLAB_TOKEN')
GITLAB_USER_LEVEL=gitlab.DEVELOPER_ACCESS
OKTA_APP_GROUP_LIST=[]
OKTA_GROUP_ID=os.getenv('OKTA_GROUP_ID') or 'My_Okta_GID'
OKTA_TOKEN=os.getenv('OKTA_TOKEN')
OKTA_URL=os.getenv('OKTA_URL') or 'https://example.okta.com/'
PARENT_GROUP_ID=30
TIMEOUT=60

# Instantiating with a Python dictionary in the constructor
config = {
    'connectionTimeout': 30,
    'orgUrl': OKTA_URL,
    'token': OKTA_TOKEN
}

gl = gitlab.Gitlab(GITLAB_URL, private_token=GITLAB_TOKEN,timeout=TIMEOUT)
okta_client = OktaClient(config)

def boot_test():
    if not GITLAB_TOKEN:
        raise Exception('GITLAB_TOKEN undefined')

    if not OKTA_TOKEN:
        raise Exception('OKTA_TOKEN undefined')

def gitlab_get_userid_from_email(
    email_address: str,
    okta_group: str = ''
    ):
    try:
        return gl.users.list(search=email_address)[0].id
    except Exception as e:
        print('INFO: GitLab User Profile Absent:', email_address)
        return None

async def unpack_okta_groups(
    okta_app_groups: object
    ):
    global OKTA_APP_GROUP_LIST

    for my_group in okta_app_groups:
        group_object, group_object_resp, err = await okta_client.get_group(my_group.id)
        group_name = group_object.profile.name
        group_members, group_members_resp, err = await okta_client.list_group_users(my_group.id)

        group_member_list = []
        for users in group_members:
            # Should require 'has_next()'
            okta_user_obj, okta_user_obj_resp, err = await okta_client.get_user(users.id)

            # Get GitLab UserID from Okta User Email Address
            gitlab_userid = gitlab_get_userid_from_email(okta_user_obj.profile.email,group_name)

            if gitlab_userid:
                group_member_list.append(gitlab_userid)

        OKTA_APP_GROUP_LIST.append({'name': group_name, 
                                    'id': my_group.id,
                                    'members': group_member_list})

    return None

async def okta_get_app_groups(
    okta_group_id: str
    ):
    global OKTA_APP_GROUP_LIST

    okta_app_groups, okta_app_groups_resp, err = await okta_client.list_application_group_assignments(okta_group_id)

    await unpack_okta_groups(okta_app_groups)

    while okta_app_groups_resp.has_next():
        okta_app_groups, err = await okta_app_groups_resp.next()

        await unpack_okta_groups(okta_app_groups)

    return OKTA_APP_GROUP_LIST

async def okta_get_group_users(
    okta_group_id: int
    ):

    users_in_group = []

    okta_users, okta_users_resp, err = await okta_client.list_group_users(okta_group_id)

    for user in okta_users:
        # User IDs in Group
        if gitlab_get_userid_from_email(email_address=user.profile.email):
            users_in_group.append(gitlab_get_userid_from_email(email_address=user.profile.email))

    while okta_users_resp.has_next():
        okta_users, err = await okta_client.list_group_users(okta_group_id)

        for user in okta_users:
            # User IDs in Group
            if gitlab_get_userid_from_email(email_address=user.profile.email):
                users_in_group.append(gitlab_get_userid_from_email(email_address=user.profile.email))
    
    return users_in_group

def gitlab_get_group_users(
    gitlab_group_id: int
    ):

    gitlab_group_list = []

    try:
        gitlab_group = gl.groups.get(gitlab_group_id)
        gitlab_group_members = gitlab_group.members_all.list(all=True)

        for member in gitlab_group_members:
            gitlab_group_list.append(member.id)

        return {'name': gitlab_group.name,
                'id': gitlab_group.id,
                'members': gitlab_group_list}

    except Exception as e:
        print('ERROR: While fetching GitLab Group Members:', gitlab_group['name'])
        return None

async def main():
    boot_test()

    gitlab_groups_all = gl.groups.list(all=True)
    okta_group_list = await okta_get_app_groups(OKTA_GROUP_ID)

    for my_group in okta_group_list:
        # Sanitise: Remove Special Characters
        group_exists = False
        group_name_sanitised = re.sub("\s+","",my_group['name'])
        group_name_sanitised = re.sub('[^A-Za-z0-9_-]+', '', group_name_sanitised)

        # Validate: Check if GitLab Group Exists
        for group in gitlab_groups_all:
            if group.name == group_name_sanitised:
                group_exists = True
                group_id = group.id

        if not group_exists:
            # Create New Group
            print('INFO: Creating New GitLab Group:', group_name_sanitised)
            new_group = gl.groups.create({'name': group_name_sanitised, 
                                        'path': group_name_sanitised,
                                        'parent_id': PARENT_GROUP_ID})
            group_id = new_group.id

        # Add Users to Group
        gitlab_group_user_list = gitlab_get_group_users(group_id)
        okta_group_user_list = await okta_get_group_users(my_group['id'])

        # Sets: For Easy Comparison
        gitlab_group_user_set = set(gitlab_group_user_list['members'])
        okta_group_user_set = set(okta_group_user_list)

        create_users = okta_group_user_set.difference(gitlab_group_user_set)
        remove_users = gitlab_group_user_set.difference(okta_group_user_set)

        # Fetch Group for Modification
        this_group = gl.groups.get(gitlab_group_user_list['id'])

        # Create Missing Users
        for user_id in create_users:
            user_email = gl.users.get(user_id).email
            print('INFO: Create New User in Group:', user_email, '@', group_name_sanitised)
            this_group.members.create({'user_id': user_id,
                                      'access_level': GITLAB_USER_LEVEL})

        # Remove Absent Users
        for user_id in remove_users:
            if user_id != 1:
                user_email = gl.users.get(user_id).email
                print('INFO: Remove User from Group:', user_email, '@', group_name_sanitised)
                this_group.members.delete(user_id)

loop = asyncio.get_event_loop()
loop.run_until_complete(main())
