
#include <iostream>
#include <cstdio>
#include <cstring>
using namespace std;
double s[50001],a[50001];
int main()
{
    int n,i,j,k;
    memset(s,0,sizeof(s));
    memset(a,0,sizeof(a));
    for(i=1;i<=50000;i++)
        a[i]=a[i-1]+1.0/i;
    for(i=1;i<=50000;i++)
        s[i]=s[i-1]+a[i]*2-1;
    scanf("%d",&n);
        printf("%.2lf\n",s[n]);
    for (i=1;i<=n;i++)
    {
        
        j=i;
        k=i; 
        while(j)
        {
            printf("1/%d ",j);
            j--;
        }
        while(n-k)
        {
            printf("1/%d ",j+2);
            j++;
            k++;
        }
        printf("\n");
    }
    return 0;
}
