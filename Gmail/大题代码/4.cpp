#include <iostream>
#include <stdio.h>
#include <cstring>

using  namespace  std;

int n,T,bag[10000],val[10000],flag=0;

void beibao(int bl,int num)
{
    val[num]=bl;
    int sum=0;
    for(int i=1;i<=n;i++) sum=sum+bag[i]*val[i];
    if (T==sum)
    {
        flag++;
        return ;
    }
    if (T<sum)
    {
        val[num]=0;
    }
    if (num+1<=n)
    {
        beibao(1,num+1);
        beibao(0,num+1);  
    }
                                            
}

int main()
{   
    int i;
    cin>>n>>T;
    for(i=1;i<=n;i++)
        cin>>bag[i];
    memset(val,0,sizeof(val));
    beibao(1,1);
    beibao(0,1);
    printf("%d\n",flag);
    return 0;
}
